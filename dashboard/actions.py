"""subprocess·async 액션 — Snapshot fresh 보장, fetch_sim.

ensure_fresh_snapshot 가 핵심: dashboard 의 HTTP middleware (`app.py::_preflight_pull`) 가
페이지 GET 요청 전에 호출. 룰:
  - in-flight pull 있으면 같은 task 를 await — 중복 SSH 회피 + freshness 이벤트 유실 없음
  - 마지막 pull 완료 후 TTL (기본 60초) 이내면 skip
  - 아니면 새 pull task 시작 후 await

기존 "task 진행 중 = 요청 버림" 정책은 navigation 흐름에서 사용자가 stale 데이터를 보는
원인이었음 (Codex 분석 결과). 이번에 "task 진행 중 = 완료 관찰" 로 바꿈.

fetch_sim 은 inspector.fetch_sim 을 직접 await — adapter 가 비동기라 같은 event loop 안전.
"""
from __future__ import annotations

import asyncio
import sys
import time
from typing import Any, Optional

from bot import inspector
from dashboard.shell import async_run
from dashboard.state import snapshot_paths, ROOT


_pull_task: Optional[asyncio.Task[dict[str, Any]]] = None
# 마지막으로 완료된 pull 의 result 와 완료 시각. TTL skip 경로에서 그대로 반환 — 직전 pull 이
# 실패였으면 TTL 만료 전엔 계속 실패 결과 노출 (stale snapshot 을 fresh 처럼 보이는 사고 방지).
# 초기값 ok=False — TTL 조건이 비정상적으로 충족돼서 첫 pull 전에 반환되는 경우에도
# 사용자가 fresh 라고 오인하지 않도록.
_last_pull_result: dict[str, Any] = {"ok": False, "skipped": True, "reason": "no_pull_yet"}
_last_pull_completed_at: float = 0.0
_PULL_TTL_SEC = 60.0


async def _pull_inner() -> dict[str, Any]:
    cmd = [sys.executable, str(ROOT / "scripts" / "inspect_subs.py"), "pull"]
    return await async_run(cmd)


def _on_pull_done(task: asyncio.Task[dict[str, Any]]) -> None:
    """task 완료(또는 cancel/exception) 시 한 번 발사 — caller fate 와 무관하게 state 갱신.

    caller A·B 가 모두 cancel 돼도 task 자체는 `asyncio.shield` 로 살아남아 정상 완료.
    이 callback 이 그 결과를 _last_pull_result 에 캐시 → 후속 TTL skip 이 stale 안 됨.
    """
    global _last_pull_result, _last_pull_completed_at
    try:
        _last_pull_result = task.result()
    except BaseException as e:  # noqa: BLE001
        _last_pull_result = {
            "ok": False, "error": f"{type(e).__name__}: {e}", "output": str(e),
        }
    _last_pull_completed_at = time.monotonic()


async def ensure_fresh_snapshot(*, ttl: float = _PULL_TTL_SEC,
                                 force: bool = False) -> dict[str, Any]:
    """Snapshot fresh 보장 후 반환.

    반환 dict 키:
      ok (bool)        — pull 또는 skip 성공 여부
      skipped (bool)   — TTL 내라 실제 pull 안 한 경우 True
      reason (str)     — "within_ttl" / "no_pull_yet" / 없음
      rc, output       — 실제 pull 한 경우 subprocess 결과
      trace_id         — async_run 이 trace 활성화 시 부여

    force=True 면 TTL 무시.

    race 처리:
      - in-flight 검사 ~ task 할당까지 await 없음 → asyncio single-threaded 에서 atomic
      - caller cancellation 안전: state 갱신은 task done callback 으로 caller 와 분리
      - pull 실패도 _last_pull_result 에 저장 → TTL skip 시 stale 로 오인 X
    """
    global _pull_task

    # in-flight 가 있으면 같은 task 결과를 공유 — 중복 SSH 회피, freshness 유실 없음.
    if _pull_task is not None and not _pull_task.done():
        return await asyncio.shield(_pull_task)

    if not force and time.monotonic() - _last_pull_completed_at < ttl:
        # 직전 결과를 그대로 — ok=True/skipped 든 ok=False/error 든 캐시된 진실 그대로 노출.
        # skipped 표시는 cache hit 임을 알리는 용도 (badge 는 ok 값으로 판단).
        cached = dict(_last_pull_result)
        cached["skipped"] = True
        cached.setdefault("reason", "within_ttl")
        return cached

    task = asyncio.create_task(_pull_inner())
    task.add_done_callback(_on_pull_done)
    _pull_task = task
    return await asyncio.shield(task)


async def run_fetch(slug: str, n: int = 5) -> dict[str, Any]:
    """inspector.fetch_sim 직접 호출 — snapshot config 로 시뮬. snapshot 의 state 만 갱신
    (라이브 N100 안 건드림). 결과 = post list 또는 None (config 없음).

    키 이름이 `items` 면 Jinja 에서 `dict.items` 메서드와 충돌해 attr lookup 이 깨짐 — `posts` 사용.
    """
    paths = snapshot_paths()
    try:
        sample = await inspector.fetch_sim(paths, slug, n=n)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "posts": []}
    if sample is None:
        return {"ok": False, "error": "config 없음 — snapshot pull 했는지 확인.", "posts": []}
    return {"ok": True, "posts": sample, "error": None}
