"""subprocess·async 액션 — page-scoped snapshot pull + fetch_sim.

핵심: 각 페이지가 필요로 하는 source 만 게이트로 통과시킴 — 전체 8s pull 안 함.

source = 5개 (bot_db / poll_state / configs / usage_db / learned). 매 page GET 직전
middleware 가 그 페이지의 needed sources 만 골라 `ensure_sources_fresh(needed)` 호출.

freshness 판단: N100 의 마커 (파일 mtime/sha1) vs 로컬 캐시된 마커. 다른 source 만 pull.
- 모든 source 안 변경 → ssh marker 1번 (~0.5s) 만 발생
- 일부 source 변경 → 그 source 만 pull
- 캐시 hit + 다른 in-flight 요청 → asyncio.shield 로 task 공유 (중복 ssh 회피)

기존 `ensure_fresh_snapshot` 은 shim 으로 남김 — startup lifespan 등이 그대로 호출.
"""
from __future__ import annotations

import asyncio
import sys
import time
from typing import Any, Iterable, Optional

from bot import inspector
from dashboard.shell import async_run
from dashboard.state import snapshot_paths, ROOT

# inspect_subs 모듈에서 SOURCE_NAMES / PULLERS / fetch_markers 재사용.
sys.path.insert(0, str(ROOT))
from scripts import inspect_subs as _isubs  # noqa: E402

ALL_SOURCES: tuple[str, ...] = _isubs.SOURCE_NAMES  # ("bot_db","poll_state","configs","usage_db","learned")


# --------------------------------------------------------------------------- #
# 상태
# --------------------------------------------------------------------------- #
# source 별 마지막으로 성공적으로 pull 된 시점의 N100 마커. cache hit 판정용.
_last_markers: dict[str, str] = {}

# source 별 in-flight pull task. 동시 nav 가 같은 source 를 두 번 안 당기게.
_pull_tasks: dict[str, asyncio.Task[bool]] = {}

# 마지막 마커 fetch 결과 + 시점. 매우 짧은 TTL 로 동시 nav 들이 ssh marker 도 한 번만 보게.
_MARKER_TTL_SEC = 2.0
_last_marker_fetch_at: float = 0.0
_last_marker_result: dict[str, str] = {}
_marker_lock = asyncio.Lock()


async def _fetch_markers_cached() -> dict[str, str]:
    """N100 5-source 마커 fetch. 2초 micro-cache 로 burst 보호.

    빈 dict 반환 = ssh 실패. 호출자는 보수적으로 (cache hit 유지) 처리.
    """
    global _last_marker_fetch_at, _last_marker_result
    async with _marker_lock:
        now = time.monotonic()
        if now - _last_marker_fetch_at < _MARKER_TTL_SEC and _last_marker_result:
            return _last_marker_result
        # to_thread 로 sync fetch_markers 호출 — 내부에서 ssh subprocess.
        m = await asyncio.to_thread(_isubs.fetch_markers)
        if m:
            _last_marker_result = m
            _last_marker_fetch_at = now
        return m


async def _pull_one(source: str) -> bool:
    """단일 source pull. asyncio.to_thread 로 sync puller 호출.

    동시 caller 가 같은 source 요청하면 in-flight task 공유 (shield).
    완료 후 task 제거 — 다음 호출은 새 task.
    """
    existing = _pull_tasks.get(source)
    if existing is not None and not existing.done():
        return await asyncio.shield(existing)

    puller = _isubs.PULLERS.get(source)
    if puller is None:
        return False

    async def _run() -> bool:
        return await asyncio.to_thread(puller)

    task = asyncio.create_task(_run())
    _pull_tasks[source] = task
    try:
        return await asyncio.shield(task)
    finally:
        # task 끝났으면 dict 에서 정리. 다른 caller 가 shielded await 중이면 task 결과는 받음.
        if task.done():
            _pull_tasks.pop(source, None)


async def ensure_sources_fresh(sources: Iterable[str]) -> dict[str, Any]:
    """필요 source 들 fresh 보장 후 결과 dict 반환.

    반환 dict:
      ok: bool — 전부 ok (또는 skip) 여부
      pulled: list[str] — 실제로 pull 한 source 이름
      skipped: list[str] — 마커 일치로 skip 한 source 이름
      failed: list[str] — pull 시도했지만 실패한 source 이름
      marker_ok: bool — ssh marker fetch 성공 여부 (False 면 보수적으로 cache hit 유지)

    sources 빈 시퀀스 → ssh marker 호출조차 안 함. {ok:True, ...} 즉시 반환.
    """
    needed = tuple(s for s in sources if s in ALL_SOURCES)
    if not needed:
        return {"ok": True, "pulled": [], "skipped": [], "failed": [], "marker_ok": True}

    markers = await _fetch_markers_cached()
    marker_ok = bool(markers)

    pulled: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []

    # marker fetch 실패 → 어느 source 가 변경됐는지 모름. 보수적으로: cache 있으면 skip, 없으면 pull.
    # (서버 재시작 후 첫 nav 가 marker fetch 실패하면 일시적으로 stale 보이지만 다음 nav 에 자동 복구.)
    for src in needed:
        cur = markers.get(src) if marker_ok else None
        seen = _last_markers.get(src)
        # 마커 fetch 됐고 이전 값과 일치 → 변경 없음, skip. (마커는 실값 또는 "(none)" — 절대 빈 문자열 X.)
        if marker_ok and cur is not None and cur == seen:
            skipped.append(src)
            continue
        # 마커 fetch 실패 + 이전 캐시 존재 → 보수적 skip (stale 가능)
        if not marker_ok and seen is not None:
            skipped.append(src)
            continue
        # 그 외 → pull
        ok = await _pull_one(src)
        if ok:
            pulled.append(src)
            if marker_ok and cur is not None:
                _last_markers[src] = cur
        else:
            failed.append(src)

    return {
        "ok": not failed,
        "pulled": pulled,
        "skipped": skipped,
        "failed": failed,
        "marker_ok": marker_ok,
    }


async def ensure_fresh_snapshot(*, force: bool = False) -> dict[str, Any]:
    """전체 source 새로고침 shim. force=True 면 _last_markers 비워서 강제 재pull.

    startup lifespan 이 cold cache 채울 때 또는 사용자가 명시적 refresh 누를 때.
    """
    if force:
        _last_markers.clear()
    return await ensure_sources_fresh(ALL_SOURCES)


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
