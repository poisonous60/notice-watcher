"""subprocess·async 액션 — Pull, fetch_sim.

Pull 은 scripts/inspect_subs.py pull 을 그대로 호출 (구현 중복 회피). fetch_sim 은 inspector.fetch_sim 을
직접 await — adapter 가 비동기라 같은 event loop 에서 돌리는 게 안전.
"""
from __future__ import annotations

import sys
from typing import Any

from bot import inspector
from dashboard.shell import async_run
from dashboard.state import snapshot_paths, ROOT


async def run_pull() -> dict[str, Any]:
    """`python scripts/inspect_subs.py pull` 을 별도 프로세스로 실행. stdout/stderr·rc 캡처해 반환.

    UI 흐름: HTMX POST 가 await → 끝나면 토스트 + 페이지 새로고침. 보통 5~30 초 (SSH + scp).
    Windows 호환성은 `dashboard.shell.async_run` 이 담당.
    """
    cmd = [sys.executable, str(ROOT / "scripts" / "inspect_subs.py"), "pull"]
    return await async_run(cmd)


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
