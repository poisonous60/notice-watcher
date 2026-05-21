"""batch hand-config 위임 파티셔너 (#2 batch).

FAILED 큐의 slug 들을 *겹침 없는* 세션-크기 청크로 나눠 codex 에 병렬 위임한다.
slug별 분할 X (같은 플랫폼끼리 recognizer/engine fix 가 겹쳐 병렬 충돌) →
**응집 키(플랫폼 또는 host)로 그룹** = 한 청크 = 한 codex 세션 (공유 fix 1회).
공유 인덱스(INDEX.md·cases.sqlite3·git)는 Claude 가 청크 수집 후 직렬 처리.

응집 키 우선순위:
  1. recognize(url) 매칭 → 그 플랫폼 NAME (같은 플랫폼 = 한 세션)
  2. 미매칭 → host (같은 사이트 = 한 세션)
  단일 host/플랫폼이면 그 자체로 1-slug 청크 (다른 청크와 파일 안 겹침 → 병렬 안전).

Usage:
  python scripts/codex_batch.py plan                       # FAILED 큐 → 청크 분할 표 (dry-run)
  python scripts/codex_batch.py plan --slugs a,b,c          # 명시 slug 목록
  python scripts/codex_batch.py emit                        # 청크별 프롬프트 파일 생성
  python scripts/codex_batch.py launch --max 3              # 청크별 보이는 창 (동시 최대 3)

launch 후 완료 감지: 각 result 파일에 python scripts/codex_watch.py <result> --loop.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import codex_handoff  # noqa: E402  (build_handconfig_batch / write_prompt / launch)


def _failed_slugs() -> list[str]:
    d = ROOT / "output" / "poll_state"
    return sorted(p.name[: -len(".FAILED.json")] for p in d.glob("*.FAILED.json"))


def _load_failed(slug: str) -> dict | None:
    p = ROOT / "output" / "poll_state" / f"{slug}.FAILED.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _cohesion_key(url: str) -> str:
    """응집 키: recognize 플랫폼 NAME, 없으면 host."""
    try:
        from engine.recognizers import recognize
        res = recognize(url)
        if res:
            # recognize 반환 형태에 따라 platform/site 추출 (dict 또는 객체)
            name = None
            if isinstance(res, dict):
                name = res.get("_recognizer") or res.get("site") or res.get("board")
            if name:
                return f"platform:{name}"
    except Exception:  # noqa: BLE001 — recognize 실패해도 host 폴백
        pass
    host = urlsplit(url).netloc or "unknown"
    return f"host:{host}"


def partition(slugs: list[str]) -> "OrderedDict[str, list[dict]]":
    """slug → 응집키 그룹. 반환: {group_key: [{slug,url,board}, ...]}."""
    groups: "OrderedDict[str, list[dict]]" = OrderedDict()
    for slug in slugs:
        data = _load_failed(slug)
        if not data:
            continue
        url = data.get("url", "")
        member = {
            "slug": slug,
            "url": url,
            "board": (data.get("last_config") or {}).get("board"),
        }
        key = _cohesion_key(url)
        groups.setdefault(key, []).append(member)
    return groups


def cmd_plan(slugs: list[str]) -> int:
    groups = partition(slugs)
    if not groups:
        print("[codex_batch] FAILED 큐 비었음 (또는 slug 없음).")
        return 0
    print(f"[codex_batch] {len(slugs)} slug → {len(groups)} 청크 (= codex 세션):\n")
    for i, (key, members) in enumerate(groups.items(), 1):
        tag = "병렬 안전(파일 격리)" if len(members) == 1 else f"{len(members)} slug 한 세션(공유 fix)"
        print(f"  청크 {i}: {key}  [{tag}]")
        for m in members:
            print(f"      - {m['slug']}  board={m.get('board') or '?'}  {m['url'][:70]}")
    print(f"\n공유 인덱스·git 은 Claude 직렬. emit/launch 로 진행.")
    return 0


def _chunk_prompt(key: str, members: list[dict]) -> Path:
    body = codex_handoff.build_handconfig_batch(members, key)
    tag = key.replace(":", "-")
    return codex_handoff.write_prompt("handconfig_batch", tag, body)


def cmd_emit(slugs: list[str]) -> int:
    groups = partition(slugs)
    for key, members in groups.items():
        path = _chunk_prompt(key, members)
        print(f"[codex_batch] {key} ({len(members)} slug) → {path}")
    print(f"\n총 {len(groups)} 청크 프롬프트. launch 로 창 띄우기.")
    return 0


def cmd_launch(slugs: list[str], max_parallel: int) -> int:
    groups = partition(slugs)
    items = list(groups.items())
    print(f"[codex_batch] {len(items)} 청크 launch (동시 최대 {max_parallel}).")
    print("각 창은 codex 세션. 완료 감지 = result 파일 polling.\n")
    launched: list[tuple[str, Path]] = []
    for key, members in items:
        path = _chunk_prompt(key, members)
        result = codex_handoff.launch(path, f"batch: {key}")
        launched.append((key, result))
        print(f"  launched {key}: result={result}")
    print("\n완료 감지 (각각):")
    for key, result in launched:
        print(f"  python scripts/codex_watch.py {result} --loop   # {key}")
    print("\n주의: 동시 실행 cap(--max)은 현재 안내용 — 모든 청크를 즉시 띄움.")
    print("실제 cap 이 필요하면 청크를 나눠 호출하거나 후속 개선(작업 큐).")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "emit", "launch"):
        p = sub.add_parser(name)
        p.add_argument("--slugs", help="쉼표구분 slug 목록 (기본: FAILED 큐 전체)")
        if name == "launch":
            p.add_argument("--max", type=int, default=3, help="동시 창 cap (현재 안내용)")
    args = ap.parse_args(argv)

    slugs = args.slugs.split(",") if getattr(args, "slugs", None) else _failed_slugs()
    slugs = [s.strip() for s in slugs if s.strip()]

    if args.cmd == "plan":
        return cmd_plan(slugs)
    if args.cmd == "emit":
        return cmd_emit(slugs)
    if args.cmd == "launch":
        return cmd_launch(slugs, args.max)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
