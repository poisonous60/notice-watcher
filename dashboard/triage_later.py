"""dev box only — `/triage/failed` 큐에서 '나중에' 토글한 slug 목록.

저장: `output/triage_later.json` ({"later": ["slug1", ...]}). git ignored.
N100 영향 0 — `<slug>.FAILED.json` 자체는 그대로 두고 dashboard view 만 분리.
수동 unsnooze only — 만료 X.

폴링은 N100 의 FAILED.json 으로 이미 재시도 차단됨 (이 모듈은 *dashboard 표시* 만 조정).
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "output" / "triage_later.json"


def load() -> set[str]:
    if not STORE.exists():
        return set()
    try:
        d = json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {str(s) for s in (d.get("later") or []) if s}


def _atomic_save(slugs: set[str]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"later": sorted(slugs)}
    fd, tmp = tempfile.mkstemp(dir=str(STORE.parent), prefix=".triage_later_", suffix=".json")
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


def add_many(slugs: list[str]) -> set[str]:
    cur = load()
    cur.update(s for s in slugs if s)
    _atomic_save(cur)
    return cur


def remove_many(slugs: list[str]) -> set[str]:
    cur = load()
    cur.difference_update(slugs)
    _atomic_save(cur)
    return cur
