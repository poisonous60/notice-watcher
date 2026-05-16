"""백그라운드 잡 worker — register/re-probe 잡 큐를 FIFO 로 직렬 처리.

- bot/main.py 의 setup_hook 에서 start() 호출 → 단일 asyncio task 로 영원히 돈다.
- 잡 1개 처리 = chromium_lock 잡고 register.py subprocess (~30초+). 끝나면 ack 메시지 edit.
- /watch 의 ack 는 채널 메시지 edit (interaction token 만료와 무관).
- /preview 의 ack 는 followup DM (ephemeral interaction 의 한계로 채널 edit 안 됨).
- re-probe 잡은 ack 없음 — 실패 시 OWNER DM (쿨다운).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable, Optional

from bot import db
from bot.runtime_config import settings
from bot.site_ops import (
    append_triage_queue,
    baseline_count,
    body_warning,
    is_rejected,
    rejected_info,
    blocking_register,
    edit_channel_message,
    is_registered,
    make_example,
)

log = logging.getLogger("bot.worker")

_task: Optional[asyncio.Task] = None


async def start(client, conn, *, dm_owner: Callable[..., Awaitable[None]]) -> None:
    """봇 ready 직후 호출. running 잡 → pending 으로 reset 하고 단일 worker task 띄움.

    DB conn 은 main asyncio thread 에서만 사용 — sqlite3 의 same-thread 검증 통과를 위해
    worker 도 to_thread 안 거치고 직접 호출. sqlite WAL + 짧은 쿼리라 event loop block 미세.
    """
    global _task
    n_reset = db.reset_running_to_pending(conn)
    if n_reset:
        log.info("worker start: %d개 running 잡을 pending 으로 reset (이전 인스턴스 잔재)", n_reset)
    if _task is not None and not _task.done():
        log.info("worker 이미 실행 중 — 재시작 안 함")
        return
    _task = asyncio.create_task(_loop(client, conn, dm_owner), name="bot.worker")
    log.info("worker task 시작")


async def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None


async def _loop(client, conn, dm_owner: Callable[..., Awaitable[None]]) -> None:
    while True:
        try:
            job = db.claim_next_pending(conn)
            if job is None:
                await asyncio.sleep(settings.worker.idle_poll_seconds)
                continue
            await _process_job(client, conn, job, dm_owner)
        except asyncio.CancelledError:
            log.info("worker 종료 (cancel)")
            return
        except Exception as e:  # noqa: BLE001
            log.exception("worker loop 예외: %r", e)
            await asyncio.sleep(settings.worker.idle_poll_seconds)


async def _process_job(client, conn, job, dm_owner) -> None:
    import sys as _sys
    from engine.tracing import start_trace
    job_id = int(job["id"])
    kind = job["kind"]
    url = job["url"]
    slug = job["slug"]
    article_url = job["article_url"]
    log.info("잡 #%d 시작 — kind=%s slug=%s url=%s", job_id, kind, slug, url)
    # probe trace 시작 — register.py subprocess 가 env 로 trace_id 받아 inner spans 추가.
    # job kind "register" → trace kind "probe", job kind "reprobe" → trace kind "probe_reprobe".
    trace_kind = "probe_reprobe" if kind == "reprobe" else "probe"
    trace_attrs = {
        "job_id": job_id, "job_kind": kind, "slug": slug, "url": url,
        "via": (job["via"] or ""),
        "article_url": article_url or "",
    }
    trace_cm = start_trace(trace_kind, attrs=trace_attrs)
    _job_exc: Optional[BaseException] = None
    try:
        # __enter__ 는 try 안 — 만약 raise 하면 finally 가 안 부서지고 __exit__ skip.
        trace_cm.__enter__()
        # enqueue 직후 owner 가 /admin reject 박은 race condition — register subprocess 안 돌리고 fail.
        if kind == "register" and is_rejected(slug):
            info = rejected_info(slug) or {}
            log.info("잡 #%d rejected by admin — register subprocess 스킵 (slug=%s)", job_id, slug)
            db.mark_job_finished(conn, job_id, ok=False, rc=-4, tail="(rejected by admin)")
            if job["ack_channel_id"]:
                await edit_channel_message(
                    client, job["ack_channel_id"], job["ack_message_id"],
                    f"❌ 이 사이트는 등록이 거부됐어요 — `{slug}`\n"
                    f"• 사유: {info.get('reason') or '-'}\n"
                    f"• 메모: {info.get('note') or '없음'}")
            return
        # 동시에 두 사용자가 같은 신규 사이트를 enqueue 한 경우 — 두 번째 잡은 register subprocess 스킵.
        if kind == "register" and is_registered(slug):
            log.info("잡 #%d 이미 등록된 사이트 — register subprocess 스킵", job_id)
            db.mark_job_finished(conn, job_id, ok=True, rc=0, tail="(already registered)")
            await _post_register_success(client, conn, job)
            return

        # ack — 처리 시작 표시 (register 만). 곧 [PHASE] probe / recognize 가 와서 덮어쓴다.
        if kind == "register" and job["ack_channel_id"]:
            await edit_channel_message(client, job["ack_channel_id"], job["ack_message_id"],
                                       f"🔎 사이트 분석 중… — `{slug}`")

        # register subprocess 가 stdout 에 찍는 [PHASE] <label> 을 받아 ack 메시지를 갱신.
        # blocking_register 는 to_thread 위에서 도니까 콜백도 그 워커 스레드에서 호출됨 — asyncio
        # loop 에 schedule 하려면 run_coroutine_threadsafe.
        on_phase = None
        if kind == "register" and job["ack_channel_id"]:
            loop = asyncio.get_running_loop()
            ch_id = job["ack_channel_id"]
            msg_id = job["ack_message_id"]

            def on_phase(label: str) -> None:  # noqa: F811  - 의도된 재바인딩
                msg = _phase_to_message(label, slug)
                if msg is None:
                    return
                asyncio.run_coroutine_threadsafe(
                    edit_channel_message(client, ch_id, msg_id, msg),
                    loop,
                )

        # reprobe 면 recognizer 우회 — 깨진 사이트를 같은 fast-path 로 무한 재진입하는 거 차단.
        rc, tail = await asyncio.to_thread(
            blocking_register, url, article_url, no_recognize=(kind == "reprobe"),
            on_phase=on_phase,
        )
        ok = (rc == 0) and is_registered(slug)
        db.mark_job_finished(conn, job_id, ok=ok, rc=rc, tail=tail)
        log.info("잡 #%d 종료 — rc=%d ok=%s", job_id, rc, ok)

        if ok:
            if kind == "register":
                await _post_register_success(client, conn, job)
            else:
                log.info("re-probe 성공 — slug=%s", slug)
        else:
            if kind == "register":
                req_by = json.loads(job["requested_by"]) if job["requested_by"] else None
                # rc=3 (register.py 의 _board_shape_check 가 게시판 아님 단정) — triage 큐 오염 막기 위해 안 쌓는다.
                # 사용자에겐 게시판/공지 페이지 URL 을 달라고 친절히 안내.
                if rc == 3:
                    await edit_channel_message(
                        client, job["ack_channel_id"], job["ack_message_id"],
                        f"⚠️ 등록 거부 — `{slug}`\n"
                        "이 URL 은 게시판 형식이 아닌 것 같아요(반복되는 글 링크/목록 API/피드가 안 보임). "
                        "게시판/공지 *목록* 페이지 URL 을 주세요.")
                else:
                    append_triage_queue(url, slug, job["via"], req_by, tail)
                    err = _format_register_error(rc, tail)
                    await edit_channel_message(client, job["ack_channel_id"], job["ack_message_id"],
                                               f"⚠️ 자동 등록 실패 — `{slug}`\n{err}")
            else:
                # re-probe 실패 — OWNER 에게만 알림
                await dm_owner(
                    f"⚠️ re-probe 실패 — `{slug}`\nrc={rc}\n```\n{(tail or '')[-1500:]}\n```",
                    key=f"reprobe-fail:{slug}",
                )
    except Exception as e:  # noqa: BLE001
        # 잡 처리 중 예상 못한 예외 — running 상태로 멈추지 않도록 failed 로 finalize.
        # mark_job_finished 가 status='running' 조건이라 이미 done/failed 인 잡은 안 건드림.
        _job_exc = e
        log.exception("잡 #%d 처리 중 예외: %r", job_id, e)
        try:
            db.mark_job_finished(conn, job_id, ok=False, rc=-99, tail=f"worker exception: {e!r}")
        except Exception:  # noqa: BLE001
            pass
        if kind == "register" and job["ack_channel_id"]:
            try:
                await edit_channel_message(
                    client, job["ack_channel_id"], job["ack_message_id"],
                    f"⚠️ 처리 중 예상치 못한 오류 — `{slug}`. 관리자에게 보고됨.")
            except Exception:  # noqa: BLE001
                pass
    finally:
        # except 가 swallow 한 예외 정보는 sys.exc_info() 에 없음 — 저장해둔 _job_exc 사용.
        if _job_exc is not None:
            try:
                trace_cm.__exit__(type(_job_exc), _job_exc, _job_exc.__traceback__)
            except Exception:  # noqa: BLE001
                pass
        else:
            try:
                trace_cm.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass


def _phase_to_message(label: str, slug: str) -> Optional[str]:
    """register.py / generator.py 의 [PHASE] <label> 을 사용자 향 ack 메시지로 변환.
    label 예: "recognize", "probe", "preflight", "digest",
              "generate max=4", "gemini_attempt 2/4", "baseline".
    None 반환 시 ack 갱신 안 함 (label 미인식)."""
    if label == "recognize":
        return f"🔎 알려진 플랫폼 인식 시도 중… — `{slug}`"
    if label == "probe":
        return f"🔎 사이트 분석 중… — `{slug}`"
    if label == "preflight":
        return f"🔎 사이트 분석 중… (글 페이지 추가 분석) — `{slug}`"
    if label == "digest":
        return f"🔎 사이트 분석 중… (분석 데이터 정리) — `{slug}`"
    if label.startswith("generate "):
        return f"🛠 config 파일 만드는 중… — `{slug}`"
    if label.startswith("gemini_attempt "):
        spec = label[len("gemini_attempt "):].strip()
        return f"🛠 config 파일 만드는 중… (시도 {spec}) — `{slug}`"
    if label == "baseline":
        return f"🧷 baseline(최근 글 목록) 수집 중… — `{slug}`"
    return None


def _format_register_error(rc: int, tail: str) -> str:
    if rc == -1:
        return "다른 작업이 크롤러를 쓰는 중이라 락 대기 초과."
    if rc == -2:
        secs = int(settings.chromium_lock.register_subprocess_timeout)
        mins = secs // 60
        unit = f"{mins}분" if secs % 60 == 0 else f"{secs}초"
        return f"사이트 분석 시간 초과({unit}) — 너무 느리거나 막힌 사이트일 수 있습니다."
    last = "\n".join((tail or "").strip().splitlines()[-6:])
    return ("이 사이트는 자동 등록이 안 됩니다 — 손어댑터가 필요합니다 "
            "(docs/사이트 어댑터 추가 가이드.md).\n```\n" + last + "\n```")


async def _post_register_success(client, conn, job) -> None:
    """register 성공 후처리: subscription 추가(있으면) + 예시 알림 만들어 ack 갱신."""
    slug = job["slug"]
    url = job["url"]
    sub: Optional[dict] = None
    if job["sub_payload"]:
        try:
            sub = json.loads(job["sub_payload"])
        except Exception:  # noqa: BLE001
            sub = None
    if sub:
        db.add_subscription(
            conn,
            user_id=sub["user_id"], slug=slug, url=url,
            filter_prompt=sub.get("filter_prompt"),
            schedule=sub["schedule"],
            target_kind=sub["target_kind"], target_id=sub["target_id"],
            notify_empty=bool(sub.get("notify_empty", False)),
        )
    n = baseline_count(slug)
    warn = body_warning(slug)
    if sub:
        where = "이 채널" if sub["target_kind"] == "channel" else "내 DM"
        head = (f"✅ 등록 완료 — `{slug}`\n"
                f"• baseline {n if n is not None else '?'}건(이 글들은 '새 글' 아님)\n"
                f"• 필터: {sub.get('filter_prompt') or '없음(새 글 전부)'}\n"
                f"• 발송: 폴링 직후 즉시\n"
                f"• 알림: {where}\n"
                f"• 새 글 없을 때도 알림: {'예' if sub.get('notify_empty') else '아니오'}"
                f"{warn}")
    else:
        head = f"✅ 등록 완료 — `{slug}` (baseline {n if n is not None else '?'}건){warn}"
    await edit_channel_message(client, job["ack_channel_id"], job["ack_message_id"],
                               head + "\n\n📋 예시 알림 만드는 중…")
    example = await make_example(slug)
    if example:
        await edit_channel_message(client, job["ack_channel_id"], job["ack_message_id"],
                                   head + "\n\n📋 **예시 알림** (이런 형식으로 옵니다):\n" + example)
    else:
        await edit_channel_message(client, job["ack_channel_id"], job["ack_message_id"],
                                   head + "\n\n(예시 알림 생성은 건너뜀 — 등록은 정상)")
