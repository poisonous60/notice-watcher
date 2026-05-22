"""dev box only — `/triage/failed` 큐의 'gate-fail' 토글 slug 목록. **Later 와 별개 버킷**.

저장: `output/triage_gate_failed.json` ({"gate_failed": {slug: {url, reason, parked_at}}}). git ignored.
`scripts/triage.py` 의 `_load_gate_failed`/`_save_gate_failed` (park-gate-fail/sweep-gate-fail) 와 *같은 파일·포맷* — dashboard 토글과 CLI 가 공유.

용도: 게이트/분류 *오판* 으로 gen_fail 로 샌 것(비-게시판인데 분류기·게이트가 못 잡음) 을 치워둠.
Later(capability/render 보류)와 해소 경로가 다름 — gate-fail 은 분류기/게이트 개선 후 `sweep-gate-fail`.
N100 영향 0 — `<slug>.FAILED.json` 자체는 그대로, dashboard view·hand-config 프롬프트서만 분리.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "output" / "triage_gate_failed.json"


def load_items() -> dict[str, dict]:
    if not STORE.exists():
        return {}
    try:
        d = json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    items = d.get("gate_failed") or {}
    if not isinstance(items, dict):
        return {}
    return {str(k): (v if isinstance(v, dict) else {}) for k, v in items.items()}


def load() -> set[str]:
    """slug 집합 (view 필터용)."""
    return set(load_items().keys())


def _atomic_save(items: dict[str, dict]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"gate_failed": dict(sorted(items.items()))}
    fd, tmp = tempfile.mkstemp(dir=str(STORE.parent), prefix=".triage_gate_failed_", suffix=".json")
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


def add_many(rows: list[tuple[str, str]], reason: str = "") -> dict[str, dict]:
    """rows = [(slug, url), ...]. 이미 있으면 metadata 유지 (parked_at 보존)."""
    cur = load_items()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for slug, url in rows:
        if not slug:
            continue
        if slug in cur:
            continue  # 기존 parked_at/reason 보존
        cur[slug] = {"url": url or "", "reason": reason or "dashboard: gate/classify 오판", "parked_at": now}
    _atomic_save(cur)
    return cur


def remove_many(slugs: list[str]) -> dict[str, dict]:
    cur = load_items()
    for s in slugs:
        cur.pop(s, None)
    _atomic_save(cur)
    return cur
