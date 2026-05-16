"""subprocess·async 액션 — Pull, fetch_sim.

Pull 은 scripts/inspect_subs.py pull 을 그대로 호출 (구현 중복 회피). fetch_sim 은 inspector.fetch_sim 을
직접 await — adapter 가 비동기라 같은 event loop 에서 돌리는 게 안전.
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any, Optional

from bot import inspector
from dashboard.shell import async_run
from dashboard.state import snapshot_paths, ROOT


# 자동 Pull (페이지 로드 hx-trigger="load") 이 새로고침마다 발사된다.
# 진행 중인 Pull 이 있으면 새 요청은 **즉시 버린다** — 큐에 쌓아 처리하면 SSH/scp 가
# 같은 snapshot 을 N번 덮어써 시간 낭비. asyncio.Lock 으로 직렬화하면 락 대기 큐가 그대로
# 누적 큐가 되므로 사용 금지. 대신 진행 중 task ref 로 check 한다.
#
# check (task is None or task.done()) 와 task 생성/할당 사이에 await 점이 없어야
# atomic 하게 동작 (asyncio 는 single-threaded — await 없이는 다른 코루틴 진입 불가).
# 따라서 검사·할당은 모두 동기 구문, await 는 그 뒤 shield 한 번만.
#
# 진행 중 handler 가 사용자 새로고침으로 cancel 돼도 subprocess 살아남게 `asyncio.shield`
# 로 감싼다 (rc=STATUS_CONTROL_C_EXIT/0xC000013A 방지).
_pull_task: Optional[asyncio.Task[dict[str, Any]]] = None


async def _pull_inner() -> dict[str, Any]:
    cmd = [sys.executable, str(ROOT / "scripts" / "inspect_subs.py"), "pull"]
    return await async_run(cmd)


async def run_pull() -> dict[str, Any]:
    """`python scripts/inspect_subs.py pull` 을 별도 프로세스로 실행. stdout/stderr·rc 캡처해 반환.

    UI 흐름: HTMX POST 가 await → 정상 완료는 app.py 가 204 로 응답해 swap 안 됨.
    실패/skip 일 때만 `#pull-result` 에 partial 주입. 자동 페이지 갱신 없음 (무한 루프 방지).
    보통 5~30 초 (SSH + scp). Windows 호환성은 `dashboard.shell.async_run` 이 담당.
    """
    global _pull_task
    # 아래 check + 할당까지 동기 — 중간에 await 없음 → atomic.
    if _pull_task is not None and not _pull_task.done():
        return {
            "ok": True,
            "rc": 0,
            "output": "이미 Pull 진행 중 — 이번 요청은 버림. 완료되면 다음 새로고침에 반영.",
            "skipped": True,
        }
    _pull_task = asyncio.create_task(_pull_inner())
    return await asyncio.shield(_pull_task)


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
