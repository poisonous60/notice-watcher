"""subprocess·async 액션 — Pull, fetch_sim.

Pull 은 scripts/inspect_subs.py pull 을 그대로 호출 (구현 중복 회피). fetch_sim 은 inspector.fetch_sim 을
직접 await — adapter 가 비동기라 같은 event loop 에서 돌리는 게 안전.
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any

from bot import inspector
from dashboard.shell import async_run
from dashboard.state import snapshot_paths, ROOT


# 자동 Pull (페이지 로드 hx-trigger="load") 이 새로고침마다 발사되므로:
#   1) lock 으로 동시 실행 직렬화 — SSH/scp 가 같은 snapshot 을 두 번 덮어쓰는 경합 차단.
#   2) 사용자가 Pull 진행 중 새로고침하면 HTMX 가 이전 요청을 abort → FastAPI handler cancel
#      → subprocess SIGINT 죽음 (rc=STATUS_CONTROL_C_EXIT/0xC000013A). 이를 막기 위해
#      실제 subprocess 실행은 별도 task 로 띄우고 `asyncio.shield` 로 감싼다. handler 가
#      cancel 돼도 inner task 는 계속 살아 lock 을 끝까지 보유 → 다음 요청은 skip 분기로 흡수.
_pull_lock = asyncio.Lock()


async def _pull_inner() -> dict[str, Any]:
    async with _pull_lock:
        cmd = [sys.executable, str(ROOT / "scripts" / "inspect_subs.py"), "pull"]
        return await async_run(cmd)


async def run_pull() -> dict[str, Any]:
    """`python scripts/inspect_subs.py pull` 을 별도 프로세스로 실행. stdout/stderr·rc 캡처해 반환.

    UI 흐름: HTMX POST 가 await → 끝나면 토스트 + 페이지 새로고침. 보통 5~30 초 (SSH + scp).
    Windows 호환성은 `dashboard.shell.async_run` 이 담당.
    """
    if _pull_lock.locked():
        return {
            "ok": True,
            "rc": 0,
            "output": "이미 Pull 진행 중 — 이번 요청은 skip. 완료되면 다음 새로고침에 반영.",
            "skipped": True,
        }
    return await asyncio.shield(_pull_inner())


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
