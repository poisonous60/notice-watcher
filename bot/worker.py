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
        # 동시에 두 사용자가 같은 신규 사이트를 enqueue 한 경우 — 두 번째 잡은 register subprocess 스킵.
        if kind == "register" and is_registered(slug):
            log.info("잡 #%d 이미 등록된 사이트 — register subprocess 스킵", job_id)
            db.mark_job_finished(conn, job_id, ok=True, rc=0, tail="(already registered)")
            await _post_register_success(client, conn, job)
            return

        # ack — 처리 시작 표시 (register 만)
        if kind == "register" and job["ack_channel_id"]:
            await edit_channel_message(client, job["ack_channel_id"], job["ack_message_id"],
                                       f"🔧 사이트 분석 중… — `{slug}`")

        rc, tail = await asyncio.to_thread(blocking_register, url, article_url)
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
    if sub:
        where = "이 채널" if sub["target_kind"] == "channel" else "내 DM"
        head = (f"✅ 등록 완료 — `{slug}`\n"
                f"• baseline {n if n is not None else '?'}건(이 글들은 '새 글' 아님)\n"
                f"• 필터: {sub.get('filter_prompt') or '없음(새 글 전부)'}\n"
                f"• 발송: 폴링 직후 즉시\n"
                f"• 알림: {where}\n"
                f"• 새 글 없을 때도 알림: {'예' if sub.get('notify_empty') else '아니오'}")
    else:
        head = f"✅ 등록 완료 — `{slug}` (baseline {n if n is not None else '?'}건)"
    await edit_channel_message(client, job["ack_channel_id"], job["ack_message_id"],
                               head + "\n\n📋 예시 알림 만드는 중…")
    example = await make_example(slug)
    if example:
        await edit_channel_message(client, job["ack_channel_id"], job["ack_message_id"],
                                   head + "\n\n📋 **예시 알림** (이런 형식으로 옵니다):\n" + example)
    else:
        await edit_channel_message(client, job["ack_channel_id"], job["ack_message_id"],
                                   head + "\n\n(예시 알림 생성은 건너뜀 — 등록은 정상)")
