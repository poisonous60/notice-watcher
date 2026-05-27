"""batch hand-config 위임 파티셔너 (#2 batch).

FAILED 큐의 slug 들을 응집 키별 세션-크기 청크로 나눠 codex 에 병렬 위임한다.
slug별 분할 X (같은 플랫폼끼리 recognizer/engine fix 가 겹쳐 병렬 충돌) →
**응집 키(플랫폼 또는 host)로 그룹** = 한 청크 = 한 codex 세션 (공유 fix 1회).
공유 인덱스(INDEX.md·cases.sqlite3·git)는 Claude 가 청크 수집 후 직렬 처리.
각 codex 세션은 worktree 에서 실행하므로 Track B 에 필요한 repo 파일은 사전 제한하지 않는다.

응집 키 우선순위:
  1. recognize(url) 매칭 → 그 플랫폼 NAME (같은 플랫폼 = 한 세션)
  2. 미매칭 → host (같은 사이트 = 한 세션)
  단일 host/플랫폼이면 그 자체로 1-slug 청크. 파일 충돌은 worktree 격리 후 Claude merge-review 에서 처리.

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
        tag = "worktree 격리" if len(members) == 1 else f"{len(members)} slug 한 세션(공유 fix, worktree 격리)"
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


def _pending_chunks(groups: "OrderedDict[str, list[dict]]") -> list[tuple[str, list[dict]]]:
    """아직 result 파일 없는(= 미처리) 청크만. 재호출 시 이미 한 청크 skip → 관측-우선 loop."""
    pending = []
    for key, members in groups.items():
        prompt_path = codex_handoff.OUT / f"codex_handconfig_batch_{codex_handoff._slugify(key.replace(':', '-'))}_prompt.txt"
        result_path = prompt_path.with_suffix(".result.md")
        if not (result_path.exists() and result_path.stat().st_size > 0):
            pending.append((key, members))
    return pending


def cmd_launch(slugs: list[str], max_parallel: int) -> int:
    """이번 호출에 *최대 max_parallel 개* 청크만 띄움 (실제 cap — spray 방지).

    default 1 = 관측-우선: 한 청크 띄우고 STOP → Claude 가 codex_watch 완료 대기 →
    diff 검토 → commit → 다음 wave 위해 launch 재호출 (이미 result 있는 청크는 skip).
    --max N 으로 신뢰 후 병렬 확대.
    """
    groups = partition(slugs)
    if not groups:
        print("[codex_batch] FAILED 큐 비었음.")
        return 0
    pending = _pending_chunks(groups)
    total = len(groups)
    if not pending:
        print(f"[codex_batch] 모든 청크({total}) 이미 result 있음 — launch 할 것 없음. diff 검토·commit 단계로.")
        return 0

    wave = pending[:max_parallel]
    print(f"[codex_batch] 전체 {total} 청크 중 미처리 {len(pending)}, 이번 wave {len(wave)} 띄움 (cap={max_parallel}).")
    if max_parallel == 1:
        print("(관측-우선: 한 청크 띄움. 완료·검토·commit 후 launch 재호출하면 다음 청크.)\n")
    launched: list[tuple[str, Path]] = []
    for key, members in wave:
        path = _chunk_prompt(key, members)
        result = codex_handoff.launch(path, f"batch: {key}",
                                      worktree=True,
                                      worktree_tag=f"batch-{codex_handoff._slugify(key.replace(':', '-'))}")
        launched.append((key, result))
        print(f"  launched {key} ({len(members)} slug): result={result}")
    print("\n완료 감지 (각각):")
    for key, result in launched:
        print(f"  python scripts/codex_watch.py {result} --loop   # {key}")
    remaining = len(pending) - len(wave)
    if remaining:
        print(f"\n남은 {remaining} 청크: 이번 wave 검토·commit 후 `codex_batch.py launch` 재호출.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "emit", "launch"):
        p = sub.add_parser(name)
        p.add_argument("--slugs", help="쉼표구분 slug 목록 (기본: FAILED 큐 전체)")
        if name == "launch":
            p.add_argument("--max", type=int, default=1, help="이번 wave 에 띄울 청크 수 cap (기본 1=관측-우선; 신뢰 후 ↑)")
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
