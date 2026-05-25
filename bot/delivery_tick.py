"""발송창 tick (ADR 0006) — 봇 내부 1분 asyncio task.

매 분 깨어나 due 수신처(user_settings/channel_settings 의 deliver_at 도래 + 오늘 미발송)가 있는지
*가벼운 SQL 쿼리* 로만 확인. 있으면 scripts/deliver_due.py 를 subprocess 로 띄워 실제 flush
(LLM 요약·blocking Discord) 를 event loop 밖에서 처리 — loop 비블록 [codex HIGH].

- 분 해상도: deliver_at 비교가 'HH:MM' 단위. 60초 sleep 이라 매 분 최소 1회 tick → 모든 분 커버.
- catch-up: due 조건이 `deliver_at <= now AND last_delivered_date < today` 라, 봇이 분/시각을
  놓쳐도 다음 tick 이 그날 안에 흡수 (자정~deliver_at 사이 부팅 시 전날분은 흡수 안 됨 — 수용).
- 동시 실행 가드: 이전 deliver_due subprocess 가 아직 돌면 새로 안 띄움 (긴 발송이 다음 tick 과 겹침 방지).
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from bot import db
from engine.tracing import env_for_child

log = logging.getLogger("bot.delivery_tick")

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
KST = db.KST

_task: Optional[asyncio.Task] = None
_running_proc: Optional[asyncio.subprocess.Process] = None


async def start(conn) -> None:
    """on_ready 에서 호출. 이미 떠 있으면 재기동 안 함 (reconnect 멱등)."""
    global _task
    if _task is not None and not _task.done():
        log.info("delivery tick 이미 실행 중 — 재기동 안 함")
        return
    _task = asyncio.create_task(_loop(conn), name="bot.delivery_tick")
    log.info("delivery tick 시작 (1분 주기)")


async def stop() -> None:
    global _task
    t = _task
    _task = None
    if t:
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass


async def _run_deliver_subprocess() -> None:
    global _running_proc
    if _running_proc is not None and _running_proc.returncode is None:
        log.warning("이전 deliver_due subprocess 아직 실행 중 — 이번 tick 스킵")
        return
    import os
    child_env = {**os.environ, **env_for_child()}
    _running_proc = await asyncio.create_subprocess_exec(
        PY, str(ROOT / "scripts" / "deliver_due.py"),
        cwd=str(ROOT), env=child_env,
    )
    rc = await _running_proc.wait()
    if rc != 0:
        log.warning("deliver_due subprocess rc=%d", rc)


def _parse_notify_test_targets() -> tuple[bool, set[str]]:
    """NOTIFY_TEST_TARGETS env 파싱 (codex 2차 review MED 3). scripts/deliver_due._parse_test_targets
    와 동일 semantics — allow-list 밖 target 은 enqueue 안 함 (옛 subprocess path 의 NOTIFY_TEST_TARGETS
    가드 보존). 형식: 쉼표 구분 'kind:id', 특수 'owner' → 'dm:<OWNER_USER_ID>'.
    """
    import os
    raw = os.environ.get("NOTIFY_TEST_TARGETS", "").strip()
    if not raw:
        return False, set()
    out: set[str] = set()
    for tok in [t.strip() for t in raw.split(",") if t.strip()]:
        if tok.lower() == "owner":
            try:
                from bot.config import owner_user_id
                owner = owner_user_id()
                if owner:
                    out.add(f"dm:{owner}")
            except Exception:  # noqa: BLE001
                pass
            continue
        if ":" in tok:
            out.add(tok)
    return True, out


def _enqueue_due_targets(conn, *, now_hhmm: str, today_kst: str) -> int:
    """ADR 0019 Phase 2 — enqueue due delivery targets for worker processing.

    NOTIFY_TEST_TARGETS 가 설정되면 allow-list 안의 target 만 enqueue (codex 2차 review MED 3).
    allow-list 밖 target 은 dedupe_key 안 박힘 → 다음 tick 에 env 풀리면 자연 복귀.
    """
    test_mode, test_allowed = _parse_notify_test_targets()
    due = db.due_targets(conn, now_hhmm=now_hhmm, today_kst=today_kst)
    inserted = 0
    skipped_test = 0
    for target in due:
        target_kind = str(target["target_kind"])
        target_id = str(target["target_id"])
        key = f"{target_kind}:{target_id}"
        if test_mode and key not in test_allowed:
            skipped_test += 1
            continue  # allow-list 밖 → enqueue 안 함, dedupe_key 안 박음
        _job_id, newly = db.enqueue_job(
            conn,
            kind="deliver_target",
            dedupe_key=f"deliver:{target_kind}:{target_id}:{today_kst}",
            sub_payload=json.dumps(
                {"target_kind": target_kind, "target_id": target_id, "today_kst": today_kst},
                ensure_ascii=False,
            ),
        )
        if newly:
            inserted += 1
    if test_mode and skipped_test:
        log.info("delivery_tick NOTIFY_TEST_TARGETS skip — %d targets outside allow-list", skipped_test)
    return inserted


async def _loop(conn) -> None:
    while True:
        try:
            await asyncio.sleep(60)
            now_kst = datetime.now(KST)
            now_hhmm = now_kst.strftime("%H:%M")
            today = now_kst.strftime("%Y-%m-%d")
            n = _enqueue_due_targets(conn, now_hhmm=now_hhmm, today_kst=today)
            if n:
                log.info("발송창 도래 — deliver_target job %d건 enqueue", n)
        except asyncio.CancelledError:
            log.info("delivery tick 종료 (cancel)")
            return
        except Exception as e:  # noqa: BLE001
            log.exception("delivery tick 예외: %r", e)
            await asyncio.sleep(5)
