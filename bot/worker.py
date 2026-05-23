"""백그라운드 잡 worker — register/re-probe 잡 큐를 pool_size 개 task 가 병렬 처리.

- bot/main.py 의 setup_hook 에서 start() 호출 → settings.worker.pool_size 개 asyncio task 로 영원히 돈다.
- 잡 1개 처리 = chromium_lock(slots=settings.chromium_lock.slots) 잡고 register.py subprocess (~30초+).
  끝나면 ack 메시지 edit.
- /watch 의 ack 는 채널 메시지 edit (interaction token 만료와 무관).
- /preview 의 ack 는 followup DM (ephemeral interaction 의 한계로 채널 edit 안 됨).
- re-probe 잡은 ack 없음 — 실패 시 OWNER DM (쿨다운).

worker 끼리 race: claim_next_pending 은 SELECT-then-UPDATE WHERE status='pending' rowcount 가드라
같은 잡 두 번 안 잡힘. DB conn 은 같은 asyncio thread 에서만 사용 — pool_size 개 task 가 같은 conn
공유해도 sqlite3 same-thread 검증 통과.
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
    STATE_DIR,
    append_triage_queue,
    baseline_count,
    blocked_info,
    body_warning,
    find_registered_alias,
    is_blocked,
    marker_kind,
    public_reason,
    blocking_register,
    edit_channel_message,
    is_registered,
    make_example,
)

log = logging.getLogger("bot.worker")

_tasks: list[asyncio.Task] = []

# 같은 잡이 봇을 N회 이상 죽이면 BUG 마커 박고 자동 fail — 큐 맨앞 무한 점유 방지.
# 임계 2 = 한 번은 외부 사고 (deploy/OOM 등) 봐주고, 두 번째 죽음에 즉시 BUG (잡 자체 원인 명백).
ATTEMPTS_LIMIT = 2


def _display_title_from_state(slug: str) -> Optional[str]:
    try:
        title = json.loads((STATE_DIR / f"{slug}.json").read_text(encoding="utf-8")).get("display_title")
    except Exception:  # noqa: BLE001
        return None
    title = str(title or "").strip()
    return title or None

# per-slug 직렬화 — 같은 slug 잡 두 개를 다른 worker 가 동시 claim 했을 때 chromium probe
# 가 같은 사이트에 병렬로 못 가게. 첫 worker 가 끝나면 두 번째가 깨어나 is_registered(slug)
# 가드(_process_job 안)에 자연 매칭 → subprocess 스킵 + _post_register_success 가 subscription
# 만 추가. 첫 잡 실패면 두 번째가 fresh subprocess (거부 사유 같으면 재거부 — 기존 메커니즘).
# enqueue 시점 url_to_slug(canonical) 가 정규화 후 DB jobs.slug 에 저장 — `?page=X` 변형 등
# 자연 흡수. asyncio.Lock 객체는 단일 thread 라 setdefault 가 race-free.
_slug_locks: dict[str, asyncio.Lock] = {}


async def start(client, conn, *, dm_owner: Callable[..., Awaitable[None]]) -> None:
    """봇 ready 직후 호출. running 잡 → pending 으로 reset 하고 worker pool 띄움.

    pool_size 개 task 가 같은 큐를 공유 (claim_next_pending race-safe).
    DB conn 은 main asyncio thread 에서만 사용 — sqlite3 의 same-thread 검증 통과를 위해
    worker 도 to_thread 안 거치고 직접 호출. sqlite WAL + 짧은 쿼리라 event loop block 미세.
    """
    global _tasks
    # _tasks guard 를 reset 보다 먼저 — on_ready 는 Discord gateway reconnect 마다 호출되는데,
    # 살아있는 worker 가 처리 중인 running 잡을 reset 하면 같은 잡이 중복 처리되고
    # attempts 도 오해해서 +1 됨. worker 가 새로 뜨는 경우(첫 부팅)에만 reset.
    _tasks = [t for t in _tasks if not t.done()]
    n = max(1, int(settings.worker.pool_size))
    if len(_tasks) >= n:
        log.info("worker 이미 실행 중 (%d task ≥ pool_size=%d) — reset/재시작 안 함 (on_ready reconnect 진입 추정)",
                 len(_tasks), n)
        return
    if _tasks:
        # 부분 생존 — 일부 task 가 BaseException 등으로 죽어 pool 이 줄어든 상태.
        # 잡 reset 은 안 함(살아있는 worker 가 running 잡 처리 중일 수 있음) — 부족한 만큼만 top-up.
        missing = n - len(_tasks)
        log.warning("worker 부분 생존 (%d/%d alive) — %d 개 top-up", len(_tasks), n, missing)
        for i in range(missing):
            _tasks.append(asyncio.create_task(
                _loop(client, conn, dm_owner), name=f"bot.worker.topup.{i}"))
        return
    n_reset = db.reset_running_to_pending(conn)
    if n_reset:
        log.info("worker start: %d개 running 잡을 pending 으로 reset (이전 인스턴스 잔재)", n_reset)
    for i in range(n):
        _tasks.append(asyncio.create_task(_loop(client, conn, dm_owner), name=f"bot.worker.{i}"))
    log.info("worker task 시작 — pool_size=%d (chromium_lock.slots=%d)",
             n, settings.chromium_lock.slots)


async def stop() -> None:
    """Best-effort cooperative stop — asyncio task 만 cancel.

    경고: `_process_job` 안의 `asyncio.to_thread(blocking_register, ...)` 는 OS thread 에서 돌고
    `chromium_lock` 도 그 thread 가 잡고 있음. asyncio cancel 은 thread 를 멈추지 않음 —
    register.py subprocess + flock 은 subprocess 자체가 끝날 때까지 계속 살아 있다.
    `stop()` await 가 풀려도 thread 가 백그라운드에서 lock 잡은 채 마저 도는 상태 가능.
    프로세스 SIGTERM 직전 호출이면 thread 가 mid-subprocess 로 버려질 수 있음 — 이 경우
    chromium_lock fd 는 interpreter shutdown 시 OS 가 회수, register.py subprocess 는 parent
    종료 시 SIGHUP 또는 그대로 orphan (start_new_session=True 라 process group leader).
    """
    global _tasks
    tasks = _tasks
    _tasks = []
    for t in tasks:
        t.cancel()
    for t in tasks:
        try:
            await t
        except asyncio.CancelledError:
            pass


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
    """slug 단위 직렬화 wrapper. 본문은 `_process_job_inner` — 락 잡고 호출.

    같은 slug 의 잡이 다른 worker 에서 진행 중이면 끝날 때까지 await. 끝난 뒤 깨어나
    `_process_job_inner` 가 자체적으로 is_blocked / is_registered 가드 통과 → 적절한 결과.
    """
    job_id = int(job["id"])
    slug = job["slug"]
    lock = _slug_locks.setdefault(slug, asyncio.Lock())
    if lock.locked():
        log.info("잡 #%d slug=%s — 같은 slug 다른 worker 처리 중, 끝날 때까지 대기", job_id, slug)
    async with lock:
        await _process_job_inner(client, conn, job, dm_owner)


async def _process_job_inner(client, conn, job, dm_owner) -> None:
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
        # is_blocked 가드 (진입~claim race 흡수) — REJECTED/FAILED/BUG 마커 중 하나라도 있으면 즉시 종결.
        # register: 같은 slug 첫 잡이 영구 거부/자동등록 실패/BUG 박은 직후 두 번째 잡이 claim 된 케이스.
        # reprobe: poll.py 가 BUG 마커 체크하지만 race (마커 박히기 전 enqueue 된 잡 + 마커 후 claim) 가능 →
        #   여기서도 가드. ADR 0001 의 "재시도 안 함" 계약을 reprobe 경로에도 강제.
        if is_blocked(slug):
            kind_m = marker_kind(slug)
            info = blocked_info(slug) or {}
            log.info("잡 #%d blocked (%s, kind=%s) — subprocess 스킵 (slug=%s)",
                     job_id, kind_m, kind, slug)
            rc_map = {"rejected": -4, "bug": -6, "failed": -7}
            db.mark_job_finished(conn, job_id, ok=False, rc=rc_map.get(kind_m, -4),
                                 tail=f"({kind_m} marker present)")
            if kind == "register" and job["ack_channel_id"]:
                if kind_m == "bug":
                    text = msg("blocked_bug", slug=slug)
                else:
                    text = msg("worker_rejected_during",
                               slug=slug,
                               reason=public_reason(info.get('reason')),
                               note=info.get('note') or '없음')
                await edit_channel_message(client, job["ack_channel_id"], job["ack_message_id"], text)
            return
        # 동시에 두 사용자가 같은 신규 사이트를 enqueue 한 경우 — 두 번째 잡은 register subprocess 스킵.
        if kind == "register" and is_registered(slug):
            log.info("잡 #%d 이미 등록된 사이트 — register subprocess 스킵", job_id)
            db.mark_job_finished(conn, job_id, ok=True, rc=0, tail="(already registered)")
            await _post_register_success(client, conn, job)
            return
        # slug 스키마 drift — 같은 board 가 다른 slug 로 이미 등록돼 있으면(recognizer 도입 등)
        # 중복 register 안 함. enqueue 전에 watch/preview 가 흡수하지만, deploy 전 큐에 쌓였거나
        # enqueue~claim 사이 다른 잡이 등록한 race 를 worker 에서도 막는다. 구독은 기존 slug 로.
        if kind == "register":
            alias = find_registered_alias(url, exclude_slug=slug)
            if alias:
                log.info("잡 #%d 같은 board 가 다른 slug(%s)로 이미 등록 — register 스킵", job_id, alias)
                db.mark_job_finished(conn, job_id, ok=True, rc=0,
                                     tail=f"(already registered as {alias})")
                await _post_register_success(client, conn, job, slug_override=alias)
                return

        # 자동 fail — 같은 잡이 봇을 ATTEMPTS_LIMIT 회 이상 죽였으면 BUG 마커 박고 종결.
        # 한 번 봐주고 (외부 사고 가능성) 두 번째 죽음에 즉시 BUG (잡 자체 원인 명백).
        if attempts >= ATTEMPTS_LIMIT:
            log.warning("잡 #%d attempts=%d 한도 %d 도달 — BUG 마커 박고 자동 fail",
                        job_id, attempts, ATTEMPTS_LIMIT)
            try:
                from scripts.register import _save_bug
                _save_bug(slug, url, rc=-5,
                          reason=f"봇이 {attempts}회 처리 중 죽음 (kind={kind})",
                          tail=f"job_id={job_id} via={job['via']}")
            except Exception as _e:  # noqa: BLE001
                log.warning("attempts 한도 _save_bug 실패 — slug=%s err=%r", slug, _e)
            db.mark_job_finished(conn, job_id, ok=False, rc=-5,
                                 tail=f"(BUG: 재시작 {attempts}회로 한도 {ATTEMPTS_LIMIT} 도달)")
            if kind == "register" and job["ack_channel_id"]:
                await edit_channel_message(
                    client, job["ack_channel_id"], job["ack_message_id"],
                    msg("blocked_bug", slug=slug))
            return

        # 봇 재시작으로 재실행된 잡 (attempts>0) → 사용자 향 재시작 안내 우선 띄움.
        # 이전 인스턴스가 ack 메시지를 phase 중간 상태(예: "사전 확인 중…")로 남겨두고 죽었을 수 있어서,
        # 다음 phase edit 가 phase 를 거꾸로 돌리는 것처럼 보이기 전에 명시적으로 "재시작 → 처음부터" 안내.
        # register 만 ack 보유 → reprobe 는 사용자 ack 없이.
        if attempts > 0 and kind == "register" and job["ack_channel_id"]:
            await edit_channel_message(
                client, job["ack_channel_id"], job["ack_message_id"],
                msg("worker_restarted", slug=slug, attempts=attempts))

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
                    # register.py 내 4 rc=3 분기 (nav_only / meta_diverging / multi_host_hub / board_shape)
                    # 가 *각자* `_save_rejected` 로 구체적 reason 의 REJECTED 마커 박음. 여기 worker 의
                    # _save_rejected 는 generic reason 으로 *덮어쓰지* 않도록 marker 없을 때만 fallback.
                    from bot.site_ops import STATE_DIR as _STATE_DIR
                    if not (_STATE_DIR / f"{slug}.REJECTED.json").exists():
                        try:
                            from scripts.register import _save_rejected
                            _save_rejected(slug, url,
                                           reason="rc=3 fallback (register 내 marker 박힘 실패 — generic 거부 사유)",
                                           note=f"requested_by={req_by} via={job['via']}")
                        except Exception as _e:  # noqa: BLE001
                            log.warning("rc=3 _save_rejected fallback 실패 — slug=%s err=%r", slug, _e)
                    await edit_channel_message(
                        client, job["ack_channel_id"], job["ack_message_id"],
                        msg("worker_board_shape_fail", slug=slug))
                elif rc == 2:
                    # policy_check 거부 (BLOCKED/LOGIN_REQUIRED) — register 가 이미 _save_rejected →
                    # `.REJECTED.json` + learned_blacklist + _prune_triage_queue 마쳤음.
                    # 여기서 append_triage_queue 다시 부르면 prune 직후 re-add 라 큐 잡음 (dashboard X / triage list O 불일치).
                    # rc=3 분기와 동일하게 triage 큐 오염 막기 위해 안 쌓는다.
                    await edit_channel_message(
                        client, job["ack_channel_id"], job["ack_message_id"],
                        msg("worker_policy_blocked", slug=slug))
                elif rc in (-1, -2, -3):
                    # 시스템 측 결함 (chromium_lock timeout / subprocess timeout / 외부 예외)
                    # = BUG 카테고리. `.BUG.json` 박고 같은 slug 후속 잡 fast-skip 시킴. OWNER DM X.
                    try:
                        from scripts.register import _save_bug
                        _save_bug(slug, url, rc=rc,
                                  reason={-1: "chromium_lock timeout",
                                          -2: "register subprocess timeout",
                                          -3: "blocking_register 외부 예외"}[rc],
                                  tail=tail or "")
                    except Exception as _e:  # noqa: BLE001
                        log.warning("rc=%d _save_bug 실패 — slug=%s err=%r", rc, slug, _e)
                    await edit_channel_message(
                        client, job["ack_channel_id"], job["ack_message_id"],
                        msg("blocked_bug", slug=slug))
                elif rc == 4:
                    # url_dead (target_not_found / cert_or_dns_broken / soft_404) — register 가 이미
                    # `_save_rejected` → `.REJECTED.json` + `_prune_triage_queue` 마쳤음. rc=2/3 와 동일하게
                    # 여기서 append_triage_queue 다시 부르면 prune 직후 re-add 라 죽은/soft-404 URL 이 work 큐
                    # 오염 (다음 batch/triage 가 이중으로 봄). 안 쌓는다. (2026-05-21 — rc=2 와 같은 버그가
                    # rc=4 split 이후 재발: docs/cases/infra_worker_rc2_triage_double_record_2026-05-17.md)
                    await edit_channel_message(
                        client, job["ack_channel_id"], job["ack_message_id"],
                        msg("worker_url_dead", slug=slug))
                else:
                    append_triage_queue(url, slug, job["via"], req_by, tail)
                    await edit_channel_message(client, job["ack_channel_id"], job["ack_message_id"],
                                               msg("worker_register_fail", slug=slug,
                                                   err=msg("worker_err_needs_hand_adapter")))
            else:
                # re-probe 실패 — OWNER 알림 안 함 (BUG 면 마커, 그 외 transient 는 다음 주기 재시도).
                if rc in (-1, -2, -3):
                    try:
                        from scripts.register import _save_bug
                        _save_bug(slug, url, rc=rc,
                                  reason={-1: "chromium_lock timeout (reprobe)",
                                          -2: "register subprocess timeout (reprobe)",
                                          -3: "blocking_register 외부 예외 (reprobe)"}[rc],
                                  tail=tail or "")
                    except Exception as _e:  # noqa: BLE001
                        log.warning("re-probe rc=%d _save_bug 실패 — slug=%s err=%r", rc, slug, _e)
                log.warning("re-probe 실패 — slug=%s rc=%d", slug, rc)
    except Exception as e:  # noqa: BLE001
        # 잡 처리 중 예상 못한 예외 — 코드 자체 결함 = BUG 카테고리. `.BUG.json` 박고 ack BUG 문구.
        # mark_job_finished 가 status='running' 조건이라 이미 done/failed 인 잡은 안 건드림.
        _job_exc = e
        log.exception("잡 #%d 처리 중 예외: %r", job_id, e)
        try:
            db.mark_job_finished(conn, job_id, ok=False, rc=-99, tail=f"worker exception: {e!r}")
        except Exception:  # noqa: BLE001
            pass
        try:
            from scripts.register import _save_bug
            _save_bug(slug, url, rc=-99,
                      reason=f"worker inner 예외: {type(e).__name__}",
                      tail=f"{e!r}")
        except Exception:  # noqa: BLE001
            pass
        if kind == "register" and job["ack_channel_id"]:
            try:
                # to_thread 가 raise 한 경우 drain 안 됐을 수 있음 — phase edit 가 BUG ack 보다
                # 늦게 land 해서 덮어쓰는 race 차단.
                await _drain_phase_edits(phase_edit_futures)
                await edit_channel_message(
                    client, job["ack_channel_id"], job["ack_message_id"],
                    msg("blocked_bug", slug=slug))
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


async def _post_register_success(client, conn, job, *, slug_override: Optional[str] = None) -> None:
    """register 성공 후처리: subscription 추가(있으면) + 예시 알림 만들어 ack 갱신.

    `slug_override`: 같은 board 가 다른 slug 로 이미 등록된(alias) 경우, 구독·예시를 *그 기존 slug* 로
    건다 — job slug(중복이라 config 없음)가 아니라. 중복 폴링·끊긴 구독 방지.
    """
    slug = slug_override or job["slug"]
    url = job["url"]
    sub: Optional[dict] = None
    if job["sub_payload"]:
        try:
            sub = json.loads(job["sub_payload"])
        except Exception:  # noqa: BLE001
            sub = None
    if sub:
        display_title = db.display_title_for_slug(conn, slug) or _display_title_from_state(slug)
        db.add_subscription(
            conn,
            user_id=sub["user_id"], slug=slug, url=url,
            filter_prompt=sub.get("filter_prompt"),
            schedule=sub["schedule"],
            target_kind=sub["target_kind"], target_id=sub["target_id"],
            notify_empty=bool(sub.get("notify_empty", False)),
            display_title=display_title,
        )
        # 발송 시각 설정 행 보장 (ADR 0006) — due 쿼리 인덱스 스캔용. 기본 08:30.
        db.ensure_setting(conn, target_kind=sub["target_kind"], target_id=sub["target_id"])
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
