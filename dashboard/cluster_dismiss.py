"""dev box only — `/clusters` 에서 '안 됨/승급 불가' 로 손으로 닫은 cluster 목록.

저장: `dashboard/cluster_dismissed.json` (git 추적 — 테스트해본 판단을 re-clone·세션 넘어 보존).
N100 영향 0 — dashboard 는 dev box 전용. 닫힌 cluster 는 `/clusters` 후보에서 빠지고
`scripts/cluster_report.py` 출력에서도 빠진다 (둘 다 compute_clusters 공유).

엔트리 = {kind, key, reason, at}.
  - kind: "same_host" | "cross_host"  (compute_clusters 의 두 섹션)
  - key : 그 섹션의 cluster key (same_host=host, cross_host=path-template "{pt}{qs}")
recognize() 로 자동 봉합되는 건 애초에 후보에 안 떠서 여기 넣을 필요 없음 — 이 목록은
*recognizer 로 못/안 묶을* cluster (이종 cross-host, capability 불가 등) 전용.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "dashboard" / "cluster_dismissed.json"

KINDS = ("same_host", "cross_host")


def load_entries() -> list[dict]:
    if not STORE.exists():
        return []
    try:
        d = json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for e in d.get("dismissed") or []:
        kind, key = e.get("kind"), e.get("key")
        if kind in KINDS and key:
            out.append({"kind": kind, "key": str(key),
                        "reason": str(e.get("reason") or ""), "at": str(e.get("at") or "")})
    return out


def load_keys() -> set[tuple[str, str]]:
    """{(kind, key)} — compute_clusters 필터용."""
    return {(e["kind"], e["key"]) for e in load_entries()}


def _atomic_save(entries: list[dict]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"dismissed": sorted(entries, key=lambda e: (e["kind"], e["key"]))}
    fd, tmp = tempfile.mkstemp(dir=str(STORE.parent), prefix=".cluster_dismissed_", suffix=".json")
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


def add(kind: str, key: str, reason: str = "") -> list[dict]:
    if kind not in KINDS or not key:
        raise ValueError(f"invalid dismiss target: kind={kind!r} key={key!r}")
    entries = [e for e in load_entries() if not (e["kind"] == kind and e["key"] == key)]
    entries.append({"kind": kind, "key": key, "reason": reason, "at": date.today().isoformat()})
    _atomic_save(entries)
    return entries


def remove(kind: str, key: str) -> list[dict]:
    entries = [e for e in load_entries() if not (e["kind"] == kind and e["key"] == key)]
    _atomic_save(entries)
    return entries
