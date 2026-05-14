"""모델별 토큰 단가 표 (`output/model_prices.json`) 로드 + 비용 계산.

- 가격 변동 잦음 → 운영 머신에서 파일만 갱신하면 됨. 코드 안 건드림.
- 파일 없으면 cost = None (대시보드는 `—` 표시).
- prompt/completion 단가 분리 — completion 이 보통 4배 비쌈.
- `per` 단위: "1M" (USD per 1M tokens, 표준), "1K" 도 허용.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_PRICES = _REPO_ROOT / "model_prices.json"

_cache: dict[str, tuple[float, dict]] = {}  # path str → (mtime, data)


def _load(path: Path) -> dict:
    """파일 path 별로 (mtime, data) 캐시. 같은 mtime 의 다른 path 가 캐시 충돌 안 나도록 path 별 분리."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    key = str(path)
    cached = _cache.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    _cache[key] = (mtime, data)
    return data


def compute_cost(provider: str, model: str, prompt_tokens: int,
                 completion_tokens: int, *, prices_path: Optional[Path] = None) -> Optional[float]:
    table = _load(prices_path or _DEFAULT_PRICES)
    # lookup 키 후보: "provider:model", "model" 단독
    key_candidates = [f"{provider}:{model}", model]
    entry = None
    for k in key_candidates:
        if k in table:
            entry = table[k]
            break
    if not entry:
        return None
    try:
        p_in = float(entry["prompt"])
        p_out = float(entry["completion"])
    except (KeyError, ValueError, TypeError):
        return None
    unit = entry.get("per", "1M")
    div = 1_000_000.0 if unit == "1M" else 1_000.0
    return (prompt_tokens * p_in + completion_tokens * p_out) / div


__all__ = ["compute_cost"]
