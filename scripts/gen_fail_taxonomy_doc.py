"""bot/fail_taxonomy.py 의 `FAIL_CATALOG` → `docs/fail 분류.md` 자동 재생성.

- `python scripts/gen_fail_taxonomy_doc.py` — md 파일 덮어쓰기.
- `python scripts/gen_fail_taxonomy_doc.py --check` — 현재 파일 vs 생성 결과 비교, 다르면 exit 1
  (pre-push hook + `tests/fail_taxonomy/test_doc_drift.py` 가 사용).
"""
from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DOC_PATH = ROOT / "docs" / "fail 분류.md"


def render() -> str:
    sys.path.insert(0, str(ROOT))
    from bot.fail_taxonomy import FAIL_CATALOG, pseudo_kinds

    lines: list[str] = []
    lines.append("# fail 분류 카탈로그")
    lines.append("")
    lines.append("> ⚠️ **자동 생성 — 손으로 편집 X.**")
    lines.append(">")
    lines.append("> source: [`bot/fail_taxonomy.py`](../bot/fail_taxonomy.py) 의 `FAIL_CATALOG`")
    lines.append("> regen: `python scripts/gen_fail_taxonomy_doc.py`")
    lines.append("> drift 검증: `tests/fail_taxonomy/test_doc_drift.py` (pre-push hook 자동 실행)")
    lines.append("")
    lines.append("대시보드 `/jobs` 의 status 셀 = **fail_kind** badge + **subkind** (작은 글). 신호 의미.")
    lines.append("")
    lines.append("## 1차 분류 (fail_kind)")
    lines.append("")
    lines.append("| fail_kind | rc / 조건 | label | severity |")
    lines.append("|---|---|---|---|")
    for fk in FAIL_CATALOG:
        cond = fk.rc_doc or (f"rc={fk.rc}" if fk.rc is not None else "—")
        lines.append(f"| `{fk.name}` | {cond} | {fk.label_ko} | {fk.severity} |")
    lines.append("")
    lines.append("**pseudo-kind** (catalog 외 표시값 — `pending`/`running` 은 base status, `unknown` 은 매처 모두 미스):")
    lines.append("")
    pseudo = pseudo_kinds()
    pseudo_chunks = [f"`{k}` ({sev or '—'})" for k, sev in pseudo.items()]
    lines.append("- " + " · ".join(pseudo_chunks))
    lines.append("")
    lines.append("## 2차 분류 (subkind)")
    lines.append("")
    lines.append("- *dynamic* 표시: subkind name 이 패턴 (예: `recognizer:wikipedia_article` 처럼 capture).")
    lines.append("- fixed subkind 가 모두 미스했을 때 dynamic 매처가 잡음 — catalog 미등록 이름도 surface.")
    lines.append("")
    for fk in FAIL_CATALOG:
        if not fk.subkinds:
            continue
        lines.append(f"### {fk.name}")
        lines.append("")
        lines.append("| subkind | label | hint |")
        lines.append("|---|---|---|")
        for sk in fk.subkinds:
            tag = " *(dynamic)*" if sk.dynamic else ""
            # 파이프 문자가 hint 에 들어가면 표 깨짐 — escape.
            hint = sk.hint.replace("|", "\\|")
            label = sk.label_ko.replace("|", "\\|")
            lines.append(f"| `{sk.name}`{tag} | {label} | {hint} |")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="drift 검증: 현재 파일과 생성 결과 비교, 다르면 exit 1.")
    args = parser.parse_args()

    generated = render()

    if args.check:
        if not DOC_PATH.exists():
            print(f"FAIL: {DOC_PATH} 없음. `python scripts/gen_fail_taxonomy_doc.py` 실행 후 commit.",
                  file=sys.stderr)
            sys.exit(1)
        current = DOC_PATH.read_text(encoding="utf-8")
        if current != generated:
            print(f"FAIL: {DOC_PATH.relative_to(ROOT)} drift. "
                  f"`python scripts/gen_fail_taxonomy_doc.py` 실행 후 commit.", file=sys.stderr)
            print("--- diff (current vs generated) ---", file=sys.stderr)
            for line in difflib.unified_diff(
                current.splitlines(keepends=True),
                generated.splitlines(keepends=True),
                fromfile="current", tofile="generated",
            ):
                sys.stderr.write(line)
            sys.exit(1)
        print(f"OK: {DOC_PATH.relative_to(ROOT)} 동기됨.")
        return

    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    # newline='\n' 고정 — Windows CRLF 변환 막아 drift 안정.
    with open(DOC_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(generated)
    print(f"WROTE: {DOC_PATH.relative_to(ROOT)} ({len(generated)} bytes)")


if __name__ == "__main__":
    main()
