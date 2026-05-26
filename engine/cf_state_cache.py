"""Per-site Cloudflare interstitial state cache — polling cycle 사이 영속.

목적: CF challenge 통과/실패 verdict 를 다음 polling cycle 에서도 재사용. 첫 cycle 에 한
번 CF wait 거치고 결과 박으면, 이후 cycle 부터 detect+wait 자체 skip. polling 1000 사이트
× 100 CF × 8s = 13분/cycle 비용을 첫 cycle 이후 0 으로.

저장: `output/cf_state.json` 단일 파일. atomic rename. TTL 7일 (그 후 무효 → 재검사).
key 형식: `{host}__{board}` (engine/config_adapter.py 의 ConfigAdapter.host + .board).

값 enum: "none" | "cleared" | "turnstile" | "timeout" — engine/strategies/playwright_html 의
_wait_through_cloudflare_interstitial_async 반환과 동일.

스레드 안전: process 안 asyncio single-thread + atomic rename. 다른 process 와의 race 는
N100 single notice-poll.service 가정상 발생 X (ADR 0016).
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_CACHE_PATH = Path(os.environ.get("NW_CF_STATE_PATH", "output/cf_state.json"))
_TTL_DAYS = 7
_VERDICT_VALID = {"none", "cleared", "turnstile", "timeout"}

_cache: Optional[dict] = None   # process-global, lazy load


def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    if not _CACHE_PATH.exists():
        _cache = {"version": 1, "states": {}}
        return _cache
    try:
        data = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            _cache = {"version": 1, "states": {}}
            return _cache
        if not isinstance(data.get("states"), dict):
            data["states"] = {}
        _cache = data
        return _cache
    except Exception:  # noqa: BLE001
        _cache = {"version": 1, "states": {}}
        return _cache


def _save() -> None:
    data = _load()
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=str(_CACHE_PATH.parent),
        prefix=_CACHE_PATH.stem + ".", suffix=".tmp", delete=False,
    )
    try:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        tmp.flush()
        os.fsync(tmp.fileno())
    finally:
        tmp.close()
    os.replace(tmp.name, _CACHE_PATH)


def _is_fresh(entry: dict, *, now: Optional[float] = None) -> bool:
    ts_iso = entry.get("ts")
    if not isinstance(ts_iso, str):
        return False
    try:
        ts = datetime.fromisoformat(ts_iso.replace("Z", "+00:00")).timestamp()
    except Exception:  # noqa: BLE001
        return False
    cur = now if now is not None else time.time()
    return (cur - ts) < (_TTL_DAYS * 86400)


def get(key: str) -> Optional[str]:
    """신선한 cache state 반환 (TTL 안). None = 없음 또는 stale."""
    if not key:
        return None
    states = _load().get("states", {})
    entry = states.get(key)
    if not isinstance(entry, dict):
        return None
    if not _is_fresh(entry):
        return None
    state = entry.get("state")
    return state if state in _VERDICT_VALID else None


def put(key: str, state: str) -> None:
    """state 박고 atomic save. state must be in _VERDICT_VALID."""
    if not key or state not in _VERDICT_VALID:
        return
    data = _load()
    data["states"][key] = {
        "state": state,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    _save()
