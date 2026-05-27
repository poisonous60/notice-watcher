"""orphan 마커 정리 — recognizer 가 같은 URL 을 *다른 slug* 로 등록하면서 남긴 stale FAILED/REJECTED.

배경: recognizer(discourse/xenforo/google-news 등) 추가 시 `probe.paths.url_to_slug` 가 같은 URL 의
slug 를 `host_<...>_<hash>` → `<platform>_<host>_<hash>` 로 바꾼다(CLAUDE.md §5 rule D). 봇이
recognizer *전* 에 박은 `host_..._<hash>.FAILED.json` + `triage_queue.jsonl` 항목은 새 slug 로 등록이
끝나도 *남는다* — `_save_state` 가 정확-slug 매칭으로만 치우기 때문. 결과: dashboard `/triage` 에
이미 등록·폴링 중인 사이트가 "실패"로 계속 떠 다음 사람이 헛작업.

검출: 마커(FAILED/REJECTED)의 hash suffix(`_xxxxxxxx`)가 *등록된 config*(마커 아닌 state.json)의
hash 와 같은데 slug 가 다르면 = orphan. hash 는 url_to_slug 가 URL 로부터 결정적으로 만든 값이라
slug prefix 가 바뀌어도 보존됨 → 같은 URL 판정의 안전한 키.

기본 dry-run. `--execute` 로 마커 삭제 + triage_queue prune. output/ 런타임 데이터만 건드림.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "output" / "poll_state"
QUEUE = ROOT / "output" / "triage_queue.jsonl"

_FAILED = ".FAILED.json"
_REJECTED = ".REJECTED.json"
_BUG = ".BUG.json"
_BROKEN = ".BROKEN.json"
_HASH_RE = re.compile(r"_([0-9a-f]{8})$")


def _hash(slug: str) -> str | None:
    m = _HASH_RE.search(slug)
    return m.group(1) if m else None


def find_orphans(state_dir: Path | None = None) -> list[tuple[str, str, str]]:
    """(marker_kind, orphan_slug, registered_slug) — hash 충돌 + slug 불일치."""
    STATE_DIR = state_dir or globals()["STATE_DIR"]
    if not STATE_DIR.exists():
        return []
    reg: dict[str, str] = {}  # hash -> registered slug (마커 아닌 state.json)
    for p in STATE_DIR.glob("*.json"):
        name = p.name
        if (name.endswith(_FAILED) or name.endswith(_REJECTED)
                or name.endswith(_BUG) or name.endswith(_BROKEN)):
            continue
        slug = name[:-5]
        h = _hash(slug)
        if h:
            reg[h] = slug
    orphans: list[tuple[str, str, str]] = []
    for p in STATE_DIR.glob("*.json"):
        name = p.name
        if name.endswith(_FAILED):
            slug, kind = name[: -len(_FAILED)], "FAILED"
        elif name.endswith(_REJECTED):
            slug, kind = name[: -len(_REJECTED)], "REJECTED"
        elif name.endswith(_BUG):
            slug, kind = name[: -len(_BUG)], "BUG"
        elif name.endswith(_BROKEN):
            slug, kind = name[: -len(_BROKEN)], "BROKEN"
        else:
            continue
        h = _hash(slug)
        if h and h in reg and reg[h] != slug:
            orphans.append((kind, slug, reg[h]))
    return orphans


def _prune_queue(orphan_slugs: set[str]) -> int:
    if not QUEUE.exists():
        return 0
    kept: list[str] = []
    removed = 0
    for line in QUEUE.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            d = json.loads(s)
        except json.JSONDecodeError:
            kept.append(line)
            continue
        if (d.get("slug") or "") in orphan_slugs:
            removed += 1
        else:
            kept.append(line)
    if removed:
        QUEUE.write_text(("\n".join(kept) + "\n") if kept else "", encoding="utf-8")
    return removed


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="recognizer slug 변경으로 생긴 orphan 마커 정리.")
    ap.add_argument("--execute", action="store_true", help="실제 삭제 (기본 dry-run).")
    args = ap.parse_args(argv)

    orphans = find_orphans()
    if not orphans:
        print("[prune-orphans] orphan 0건 — 깨끗.")
        return 0

    print(f"[prune-orphans] orphan {len(orphans)}건 (등록은 다른 slug 로 됨 — 마커만 stale):")
    for kind, slug, reg in orphans:
        print(f"  {kind:9} {slug}  ->등록됨-> {reg}")

    if not args.execute:
        print(f"\n  dry-run. 실제 정리: python scripts/prune_orphans.py --execute")
        return 0

    orphan_slugs = {slug for _, slug, _ in orphans}
    n_files = 0
    _SUFFIX_BY_KIND = {"FAILED": _FAILED, "REJECTED": _REJECTED, "BUG": _BUG, "BROKEN": _BROKEN}
    for kind, slug, _ in orphans:
        suffix = _SUFFIX_BY_KIND[kind]
        f = STATE_DIR / f"{slug}{suffix}"
        try:
            f.unlink()
            n_files += 1
        except OSError as e:
            print(f"  ⚠ 삭제 실패 {f.name}: {e}", file=sys.stderr)
    n_queue = _prune_queue(orphan_slugs)
    print(f"\n[prune-orphans --execute] 마커 {n_files}개 삭제, triage_queue {n_queue}줄 prune.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
