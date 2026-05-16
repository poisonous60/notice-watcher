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
from bot.messages import render as msg
from bot.runtime_config import settings
from bot.site_ops import (
    append_triage_queue,
    baseline_count,
    body_warning,
    is_rejected,
    public_reason,
    rejected_info,
    blocking_register,
    edit_channel_message,
    is_registered,
    make_example,
)

log = logging.getLogger("bot.worker")

_task: Optional[asyncio.Task] = None

# 같은 잡이 봇을 N회 이상 죽이면 자동 failed 처리 — 큐 맨앞에서 무한 점유 방지.
ATTEMPTS_LIMIT = 5


async def start(client, conn, *, dm_owner: Callable[..., Awaitable[None]]) -> None:
    """봇 ready 직후 호출. running 잡 → pending 으로 reset 하고 단일 worker task 띄움.

    DB conn 은 main asyncio thread 에서만 사용 — sqlite3 의 same-thread 검증 통과를 위해
    worker 도 to_thread 안 거치고 직접 호출. sqlite WAL + 짧은 쿼리라 event loop block 미세.
    """
    global _task
    # _task guard 를 reset 보다 먼저 — on_ready 는 Discord gateway reconnect 마다 호출되는데,
    # 살아있는 worker 가 처리 중인 running 잡을 reset 하면 같은 잡이 중복 처리되고
    # attempts 도 오해해서 +1 됨. worker 가 새로 뜨는 경우(첫 부팅)에만 reset.
    if _task is not None and not _task.done():
        log.info("worker 이미 실행 중 — reset/재시작 안 함 (on_ready reconnect 진입 추정)")
        return
    n_reset = db.reset_running_to_pending(conn)
    if n_reset:
        log.info("worker start: %d개 running 잡을 pending 으로 reset (이전 인스턴스 잔재)", n_reset)
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


async def _drain_phase_edits(futures: list) -> None:
    """on_phase 가 run_coroutine_threadsafe 로 fire-and-forget 한 edit 코루틴 future 들을
    await 로 settle. 호출 후 list 비움.

    이유: phase edit 와 final edit 가 동시에 loop 에 있으면 Discord REST 도착 순서가 비결정 →
    final 이 먼저 가고 phase 가 나중에 가서 final 을 덮어쓰는 race 가 생긴다 (예: digest phase
    edit 가 board_shape_fail edit 보다 늦게 land → 사용자가 "분석 데이터 정리" 메시지에 stuck).
    final edit 직전에 호출해 phase edit 들이 먼저 Discord 에 도달하도록 보장.
    """
    if not futures:
        return
    for fut in futures:
        try:
            await asyncio.wrap_future(fut)
        except Exception:  # noqa: BLE001
            # 개별 edit 실패는 edit_channel_message 가 이미 warning 로깅 + False 반환 — swallow.
            pass
    futures.clear()


async def _process_job(client, conn, job, dm_owner) -> None:
    import sys as _sys
    from engine.tracing import start_trace
    job_id = int(job["id"])
    kind = job["kind"]
    url = job["url"]
    slug = job["slug"]
    article_url = job["article_url"]
    # attempts>0 = 이전 인스턴스가 running 상태로 죽었고 reset_running_to_pending 이 +1 한 뒤 재claim 된 잡.
    # 옛 DB 행은 attempts 컬럼이 없을 수 있어 keys() 체크로 안전 fetch.
    attempts = int(job["attempts"]) if "attempts" in job.keys() else 0
    log.info("잡 #%d 시작 — kind=%s slug=%s url=%s attempts=%d", job_id, kind, slug, url, attempts)
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
    # on_phase 가 run_coroutine_threadsafe 로 fire-and-forget 한 edit 코루틴들의 future.
    # fire-and-forget 라 final edit_channel_message 보다 *나중에* Discord 도달해서 final 을
    # 덮어쓰는 race 가 있었음 (예: digest phase edit 가 board_shape_fail edit 보다 늦게 land
    # → 사용자가 "분석 데이터 정리" 에 stuck). final edit 직전 await 로 settle 시킴.
    phase_edit_futures: list = []
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
                    msg("worker_rejected_during",
                        slug=slug,
                        reason=public_reason(info.get('reason')),
                        note=info.get('note') or '없음'))
            return
        # 동시에 두 사용자가 같은 신규 사이트를 enqueue 한 경우 — 두 번째 잡은 register subprocess 스킵.
        if kind == "register" and is_registered(slug):
            log.info("잡 #%d 이미 등록된 사이트 — register subprocess 스킵", job_id)
            db.mark_job_finished(conn, job_id, ok=True, rc=0, tail="(already registered)")
            await _post_register_success(client, conn, job)
            return

        # 자동 fail — 같은 잡이 봇을 ATTEMPTS_LIMIT 회 이상 죽였으면 큐 맨앞 점유 그만 두고 끝냄.
        # claim_next_pending 직후라 status='running' → mark_job_finished 의 가드 통과.
        if attempts > ATTEMPTS_LIMIT:
            log.warning("잡 #%d attempts=%d 가 한도 %d 초과 — 자동 failed 처리",
                        job_id, attempts, ATTEMPTS_LIMIT)
            db.mark_job_finished(conn, job_id, ok=False, rc=-5,
                                 tail=f"(자동 fail — 재시작 {attempts}회로 한도 {ATTEMPTS_LIMIT} 초과)")
            if kind == "register" and job["ack_channel_id"]:
                await edit_channel_message(
                    client, job["ack_channel_id"], job["ack_message_id"],
                    msg("worker_attempts_exceeded", slug=slug, attempts=attempts))
            await dm_owner(
                f"❌ 잡 #{job_id} `{slug}` 가 재시작 {attempts}회로 한도 초과 — 자동 failed. "
                "처리 중 봇이 반복 죽는 원인 조사 필요",
                key=f"job-attempts-exceeded:{job_id}",
            )
            return

        # 봇 재시작으로 재실행된 잡 (attempts>0) → 사용자 향 재시작 안내 우선 띄움.
        # 이전 인스턴스가 ack 메시지를 phase 중간 상태(예: "사전 확인 중…")로 남겨두고 죽었을 수 있어서,
        # 다음 phase edit 가 phase 를 거꾸로 돌리는 것처럼 보이기 전에 명시적으로 "재시작 → 처음부터" 안내.
        # register 만 ack 보유 → reprobe 는 사용자 ack 없이 OWNER DM 만.
        if attempts > 0 and kind == "register" and job["ack_channel_id"]:
            await edit_channel_message(
                client, job["ack_channel_id"], job["ack_message_id"],
                msg("worker_restarted", slug=slug, attempts=attempts))
        # OWNER DM 은 kind 무관 — reprobe 도 무한 재시작 가능성 관측해야 함.
        if attempts >= 2:
            await dm_owner(
                f"⚠️ 잡 #{job_id} `{slug}` (kind={kind}) 가 재시작 {attempts}회 — "
                "처리 중 봇이 반복 죽는지 확인 필요",
                key=f"job-restart:{job_id}",
            )

        # ack — 처리 시작 표시 (register 만). 곧 [PHASE] probe / recognize 가 와서 덮어쓴다.
        # attempts>0 이어서 worker_restarted 가 위에 떴어도, 이 phase_probe 가 곧 덮어써서
        # 재시작 안내가 영구 stuck 되는 위험 차단 (사용자는 "재시작…" 잠깐 → "사이트 분석 중…" 흐름).
        if kind == "register" and job["ack_channel_id"]:
            await edit_channel_message(client, job["ack_channel_id"], job["ack_message_id"],
                                       msg("worker_phase_probe", slug=slug))

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
                fut = asyncio.run_coroutine_threadsafe(
                    edit_channel_message(client, ch_id, msg_id, msg),
                    loop,
                )
                phase_edit_futures.append(fut)

        # reprobe 면 recognizer 우회 — 깨진 사이트를 같은 fast-path 로 무한 재진입하는 거 차단.
        rc, tail = await asyncio.to_thread(
            blocking_register, url, article_url, no_recognize=(kind == "reprobe"),
            on_phase=on_phase,
        )
        # fire-and-forget 한 phase edit 들을 모두 settle — 아래 final edit 보다 *나중에* Discord
        # 에 도달해서 final 을 덮어쓰는 race 차단.
        await _drain_phase_edits(phase_edit_futures)
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
                # + slug 단위 .REJECTED.json 마커 + host+path_prefix 패턴 자동 학습 (한 사용자 거부 → 모두에게 적용).
                if rc == 3:
                    try:
                        from scripts.register import _save_rejected
                        _save_rejected(slug, url,
                                       reason="board_shape_check 게이트 거부 (probe 가 같은 호스트로 가는 board 신호 못 찾음)",
                                       note=f"requested_by={req_by} via={job['via']}")
                    except Exception as _e:  # noqa: BLE001
                        log.warning("rc=3 _save_rejected 실패 — slug=%s err=%r", slug, _e)
                    await edit_channel_message(
                        client, job["ack_channel_id"], job["ack_message_id"],
                        msg("worker_board_shape_fail", slug=slug))
                elif rc == 2:
                    # policy_check 거부 (BLOCKED/LOGIN_REQUIRED) — 차단 우회는 정책상 금지 →
                    # 손어댑터 안내·tail dump 모두 거짓 신호. 짧은 한 줄 안내로 대체.
                    append_triage_queue(url, slug, job["via"], req_by, tail)
                    await edit_channel_message(
                        client, job["ack_channel_id"], job["ack_message_id"],
                        msg("worker_policy_blocked", slug=slug))
                else:
                    append_triage_queue(url, slug, job["via"], req_by, tail)
                    err = _format_register_error(rc, tail)
                    await edit_channel_message(client, job["ack_channel_id"], job["ack_message_id"],
                                               msg("worker_register_fail", slug=slug, err=err))
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
                # to_thread 가 raise 한 경우 drain 안 됐을 수 있음 — phase edit 가 unexpected 보다
                # 늦게 land 해서 덮어쓰는 race 차단.
                await _drain_phase_edits(phase_edit_futures)
                await edit_channel_message(
                    client, job["ack_channel_id"], job["ack_message_id"],
                    msg("worker_unexpected", slug=slug))
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
        return msg("worker_phase_recognize", slug=slug)
    if label == "probe":
        return msg("worker_phase_probe", slug=slug)
    if label == "preflight":
        return msg("worker_phase_preflight", slug=slug)
    if label == "digest":
        return msg("worker_phase_digest", slug=slug)
    if label.startswith("generate "):
        return msg("worker_phase_generate", slug=slug)
    if label.startswith("gemini_attempt "):
        spec = label[len("gemini_attempt "):].strip()
        return msg("worker_phase_gemini_attempt", slug=slug, spec=spec)
    if label == "baseline":
        return msg("worker_phase_baseline", slug=slug)
    return None


def _format_register_error(rc: int, tail: str) -> str:
    if rc == -1:
        return msg("worker_err_lock_timeout")
    if rc == -2:
        secs = int(settings.chromium_lock.register_subprocess_timeout)
        mins = secs // 60
        unit = f"{mins}분" if secs % 60 == 0 else f"{secs}초"
        return msg("worker_err_subprocess_timeout", unit=unit)
    last = "\n".join((tail or "").strip().splitlines()[-6:])
    return msg("worker_err_needs_hand_adapter", tail=last)


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
        head = msg("worker_success_subscribed_head",
                   slug=slug,
                   n=(n if n is not None else '?'),
                   filter=(sub.get('filter_prompt') or '없음(새 글 전부)'),
                   where=where,
                   notify_empty=('예' if sub.get('notify_empty') else '아니오'),
                   warn=warn)
    else:
        head = msg("worker_success_preview_head",
                   slug=slug,
                   n=(n if n is not None else '?'),
                   warn=warn)
    await edit_channel_message(client, job["ack_channel_id"], job["ack_message_id"],
                               head + "\n\n" + msg("watch_example_loading_suffix"))
    example = await make_example(slug)
    if example:
        await edit_channel_message(
            client, job["ack_channel_id"], job["ack_message_id"],
            head + "\n\n" + msg("watch_example_present_prefix") + "\n" + example)
    else:
        await edit_channel_message(
            client, job["ack_channel_id"], job["ack_message_id"],
            head + "\n\n" + msg("watch_example_skip"))
