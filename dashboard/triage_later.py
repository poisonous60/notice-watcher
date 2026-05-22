"""dev box only — `/triage/failed` 큐에서 '나중에' 토글한 slug 목록.

저장: `output/triage_later.json` ({"later": {slug: {reason, parked_at}}}). git ignored.
(구 포맷 {"later": [slug, ...]} 도 읽힘 — set 리더는 dict keys / list elements 둘 다 순회. 다음 save 때 dict 로 마이그.)
N100 영향 0 — `<slug>.FAILED.json` 자체는 그대로 두고 dashboard view 만 분리.
수동 unsnooze only — 만료 X.

reason = Later 전용 memo (사용자가 dashboard 에서 편집). FAILED.json 의 reason 과 별개 —
"왜 나중으로 미뤘나"(capability / IP·망 도달불가 / render 필요)를 사람이 적는 칸.

폴링은 N100 의 FAILED.json 으로 이미 재시도 차단됨 (이 모듈은 *dashboard 표시* 만 조정).
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "output" / "triage_later.json"


def load_items() -> dict[str, dict]:
    """{slug: {reason, parked_at}}. 구 list 포맷이면 reason 빈 dict 로 승격."""
    if not STORE.exists():
        return {}
    try:
        d = json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    raw = d.get("later")
    if isinstance(raw, dict):
        return {str(k): (v if isinstance(v, dict) else {}) for k, v in raw.items() if k}
    if isinstance(raw, list):  # 구 포맷 — slug 리스트
        return {str(s): {} for s in raw if s}
    return {}


def load() -> set[str]:
    """slug 집합 (view 필터·CLI 공유). dict/list 양쪽 호환."""
    return set(load_items().keys())


def _atomic_save(items: dict[str, dict]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"later": dict(sorted(items.items()))}
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


def add_many(slugs: list[str], reason: str = "") -> dict[str, dict]:
    """slug 들을 Later 로. 이미 있으면 parked_at 보존 (reason 명시 시 빈 reason 만 채움)."""
    cur = load_items()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for slug in slugs:
        if not slug:
            continue
        if slug in cur:
            if reason and not (cur[slug].get("reason") or "").strip():
                cur[slug]["reason"] = reason
            continue
        cur[slug] = {"reason": reason or "", "parked_at": now}
    _atomic_save(cur)
    return cur


def set_reason(slug: str, reason: str) -> dict[str, dict]:
    """Later memo 편집/설정 (dashboard). 없는 slug 면 새로 추가."""
    cur = load_items()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if slug in cur:
        cur[slug]["reason"] = reason
    else:
        cur[slug] = {"reason": reason, "parked_at": now}
    _atomic_save(cur)
    return cur


def remove_many(slugs: list[str]) -> dict[str, dict]:
    cur = load_items()
    for s in slugs:
        cur.pop(s, None)
    _atomic_save(cur)
    return cur
