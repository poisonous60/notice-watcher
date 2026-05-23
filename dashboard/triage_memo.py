"""dev box only — `/triage/failed` 큐의 *범용* 사람-memo. **버킷 무관** (활성·Later·게이트실패 전부).

저장: `output/triage_memo.json` ({"memo": {slug: {reason, updated_at}}}). git ignored.

Later/gate-fail 버킷 store(triage_later·triage_gate_failed)에도 reason 칸이 있지만 그건 *버킷 진입 사유*(CLI park 가 적음).
이 모듈은 dashboard 에서 사람이 어느 행에서나 자유로 다는 memo — SoT. 표시 우선순위는 app.py 가 결정
(triage_memo > 버킷 reason > FAILED.json reason). 첫 편집이 이 store 로 이관되므로 별도 마이그 불필요.
N100 영향 0 — dashboard 표시 전용.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "output" / "triage_memo.json"


def load_items() -> dict[str, dict]:
    if not STORE.exists():
        return {}
    try:
        d = json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    raw = d.get("memo")
    if not isinstance(raw, dict):
        return {}
    return {str(k): (v if isinstance(v, dict) else {}) for k, v in raw.items() if k}


def get(slug: str) -> str:
    """slug 의 memo 텍스트 (없으면 빈 문자열)."""
    return (load_items().get(slug) or {}).get("reason") or ""


def _atomic_save(items: dict[str, dict]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"memo": dict(sorted(items.items()))}
    fd, tmp = tempfile.mkstemp(dir=str(STORE.parent), prefix=".triage_memo_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STORE)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def set_memo(slug: str, reason: str) -> dict[str, dict]:
    """memo 편집/설정. 빈 문자열이면 해당 slug 제거 (빈 memo 누적 방지)."""
    cur = load_items()
    if reason:
        cur[slug] = {
            "reason": reason,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    else:
        cur.pop(slug, None)
    _atomic_save(cur)
    return cur
