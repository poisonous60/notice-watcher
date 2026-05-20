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


async def _loop(conn) -> None:
    while True:
        try:
            await asyncio.sleep(60)
            now_kst = datetime.now(KST)
            now_hhmm = now_kst.strftime("%H:%M")
            today = now_kst.strftime("%Y-%m-%d")
            due = db.due_targets(conn, now_hhmm=now_hhmm, today_kst=today)
            if due:
                log.info("발송창 도래 — due 수신처 %d건, deliver_due 호출", len(due))
                await _run_deliver_subprocess()
        except asyncio.CancelledError:
            log.info("delivery tick 종료 (cancel)")
            return
        except Exception as e:  # noqa: BLE001
            log.exception("delivery tick 예외: %r", e)
            await asyncio.sleep(5)
