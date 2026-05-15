"""docs/cases/*.md 의 YAML frontmatter 를 모아 docs/cases/INDEX.md 를 생성한다.

각 case 파일 포맷:

    ---
    slug: <slug>
    url: <url>
    status: <emoji + 설명>
    date: <YYYY-MM-DD>
    failure_keys: [...]      # 선택
    fix_layer: <E|D|C|B|A|F>  # 선택. string OR array
    config_strategy: <strategy> # 선택
    ...
    ---

    [자유 markdown 본문]

사용:
    python scripts/cases_index.py                 # docs/cases/INDEX.md 덮어씀
    python scripts/cases_index.py --output PATH   # 다른 경로로
    python scripts/cases_index.py --cases-dir DIR # 다른 디렉토리에서 읽기

`--check` 는 만들지 않음 — pre-push 강제 시 UX friction (typo fix 도 regen 강제) 발생.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    print("PyYAML 필요: pip install pyyaml", file=sys.stderr)
    sys.exit(2)


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CASES_DIR = ROOT / "docs" / "cases"
FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)


def parse_case(path: Path) -> dict | None:
    text = path.read_text(encoding="utf-8").lstrip("﻿")  # UTF-8 BOM 제거
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        print(f"WARN: {path.name} frontmatter parse 실패: {e}", file=sys.stderr)
        return None
    if not isinstance(fm, dict):
        return None
    fm["_path"] = path
    return fm


def _fmt_list(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(x) for x in value)
    return str(value)


def _fmt_layer(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "/".join(str(x) for x in value)
    return str(value)


def render_index(cases: list[dict], cases_dir: Path) -> str:
    rows: list[str] = []
    rows.append("# 사이트별 등록 시도 기록 — INDEX")
    rows.append("")
    rows.append("> 자동 생성 — `python scripts/cases_index.py` 가 `docs/cases/*.md` 의 YAML frontmatter 를 모아 만든다. **직접 편집 X**.")
    rows.append("")
    rows.append(f"총 {len(cases)} 건. 각 슬러그를 클릭하면 상세 case 파일.")
    rows.append("")
    rows.append("| slug | status | date | fix_layer | failure_keys | url |")
    rows.append("|---|---|---|---|---|---|")

    cases_sorted = sorted(
        cases,
        key=lambda c: (str(c.get("date") or ""), str(c.get("slug") or "")),
        reverse=True,
    )

    for c in cases_sorted:
        slug = c.get("slug") or c["_path"].stem
        status = c.get("status") or ""
        date = c.get("date") or ""
        layer = _fmt_layer(c.get("fix_layer"))
        keys = _fmt_list(c.get("failure_keys"))
        url = c.get("url") or ""
        # slug 링크 = 파일명 (경로 상대)
        path_name = c["_path"].name
        slug_link = f"[`{slug}`]({path_name})"
        rows.append(f"| {slug_link} | {status} | {date} | {layer} | {keys} | {url} |")

    rows.append("")
    rows.append("## 통계")
    rows.append("")

    layer_counter: Counter = Counter()
    for c in cases:
        lv = c.get("fix_layer")
        if lv is None:
            layer_counter["(미기재)"] += 1
        elif isinstance(lv, (list, tuple)):
            for x in lv:
                layer_counter[str(x)] += 1
        else:
            layer_counter[str(lv)] += 1
    rows.append("### fix_layer 분포")
    rows.append("")
    rows.append("| layer | count |")
    rows.append("|---|---|")
    for k, v in sorted(layer_counter.items()):
        rows.append(f"| {k} | {v} |")
    rows.append("")

    strategy_counter = Counter()
    for c in cases:
        s = c.get("config_strategy") or "(미기재)"
        strategy_counter[str(s)] += 1
    rows.append("### config_strategy 분포")
    rows.append("")
    rows.append("| strategy | count |")
    rows.append("|---|---|")
    for k, v in sorted(strategy_counter.items()):
        rows.append(f"| {k} | {v} |")
    rows.append("")

    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=90)).date().isoformat()
    recent = sum(1 for c in cases if str(c.get("date") or "") >= cutoff)
    rows.append(f"### 최근 90일 (≥ {cutoff})")
    rows.append("")
    rows.append(f"케이스 {recent} 건.")
    rows.append("")

    return "\n".join(rows) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="docs/cases/*.md → docs/cases/INDEX.md")
    ap.add_argument("--cases-dir", type=Path, default=DEFAULT_CASES_DIR)
    ap.add_argument("--output", type=Path, default=None)
    args = ap.parse_args()

    cases_dir: Path = args.cases_dir
    out_path: Path = args.output or (cases_dir / "INDEX.md")

    if not cases_dir.is_dir():
        print(f"cases 디렉토리 없음: {cases_dir}", file=sys.stderr)
        return 2

    paths = sorted(p for p in cases_dir.glob("*.md") if p.name != "INDEX.md")
    cases: list[dict] = []
    skipped = 0
    for p in paths:
        c = parse_case(p)
        if c is None:
            print(f"WARN: {p.name} — frontmatter 없음/파싱 실패, skip", file=sys.stderr)
            skipped += 1
            continue
        cases.append(c)

    content = render_index(cases, cases_dir)
    out_path.write_text(content, encoding="utf-8", newline="\n")
    print(f"[cases_index] {out_path.relative_to(ROOT)} — {len(cases)} 건 (skip {skipped})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
