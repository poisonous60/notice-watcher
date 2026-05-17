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
    python scripts/cases_index.py --backfill-db PATH  # output/cases.sqlite3 에 row backfill

`--check` 는 만들지 않음 — pre-push 강제 시 UX friction (typo fix 도 regen 강제) 발생.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

# bot/ 패키지 — case_runs schema 단일 진실원
_THIS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_THIS_ROOT))
from bot.case_runs_meta import SCHEMA as _SCHEMA  # noqa: E402

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


# ---------------------------------------------------------------------------- #
# Backfill — frontmatter → output/cases.sqlite3 의 case_runs 테이블
# ---------------------------------------------------------------------------- #
# schema 는 bot/case_runs_meta.py 가 단일 진실원 — 위 import 의 _SCHEMA 사용.


def _classify_outcome(status: str, fm: dict) -> list[str]:
    """frontmatter outcome (명시) 우선 → status + fix_layer 폴백 (legacy).

    표준 형식 (`docs/case_runs DB 계획.md` rev 3):
      frontmatter 에 `outcome: <improved|handcrafted|no_change|rejected|rejected_with_policy|error>`
      명시 — DB row 가 그대로 박힘. case 파일이 source-of-truth.

    legacy 폴백 (outcome 명시 X 일 때):
      fix_layer 있음 (A/B/C/D/F/G 등)        → improved (코드 일반화)
      ✅ 자동 + engine_files_touched 있음    → improved
      ✅ 손작성 / 🔧 / 🧩                    → handcrafted
      🚫                                       → rejected
      ❌ FAILED                                → error
      기타                                     → error 폴백 (warn)

    return list — 미래 split 케이스 대비 (현재 사용 X — 명시 outcome = 1 row).
    """
    # 1. 명시 outcome 우선
    explicit = fm.get("outcome")
    if explicit:
        if isinstance(explicit, str):
            return [explicit]
        if isinstance(explicit, list):
            return [str(x) for x in explicit]

    # 2. legacy 폴백
    s = status or ""
    if s.startswith("🚫"):
        return ["rejected"]
    if fm.get("fix_layer"):
        return ["improved"]
    if s.startswith("✅"):
        if "자동" in s and "손작성" not in s:
            engine_touched = fm.get("engine_files_touched") or []
            return ["improved" if engine_touched else "handcrafted"]
        return ["handcrafted"]
    if s.startswith("🔧") or s.startswith("🧩"):
        return ["handcrafted"]
    if s.startswith("❌"):
        return ["error"]
    return ["error"]


def _extract_first_paragraph(text: str, cap: int = 200) -> str:
    """frontmatter 이후 본문의 첫 단락 (첫 ## 섹션 본문) — reason 폴백."""
    body = text
    m = FRONTMATTER_RE.match(text)
    if m:
        body = text[m.end():]
    # 첫 ## 섹션 찾기 — 그 안 첫 단락
    section_match = re.search(r"^##\s+[^\n]+\n([^\n].+?)(?:\n\n|\n##|\Z)", body, re.S | re.M)
    if section_match:
        para = section_match.group(1).strip()
    else:
        # 없으면 본문 첫 단락
        para = body.strip().split("\n\n", 1)[0].strip()
    para = re.sub(r"\s+", " ", para)
    if len(para) > cap:
        para = para[:cap].rstrip() + "…"
    return para or "(본문 없음)"


def _git_commit_for_slug(slug: str) -> str | None:
    return _git_log_field_for_slug(slug, "%H")


def _git_commit_iso_time_for_slug(slug: str) -> str | None:
    """slug 가 commit 메시지에 박힌 commit 의 committer 시각 (ISO 8601, UTC `Z`).
    ts 컬럼 source-of-truth — frontmatter date midnight 보다 정밀 (정렬 안정성)."""
    iso = _git_log_field_for_slug(slug, "%cI")
    if not iso:
        return None
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(iso).astimezone(timezone.utc)
        # `YYYY-MM-DDTHH:MM:SSZ` — sqlite TEXT lex 정렬 == 시각 정렬.
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return None


def _git_log_field_for_slug(slug: str, fmt: str) -> str | None:
    try:
        r = subprocess.run(
            ["git", "log", "-1", f"--pretty={fmt}", "--grep", slug],
            cwd=str(ROOT),
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return None
        out = r.stdout.strip()
        return out or None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _fmt_layer_str(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return "+".join(str(x) for x in value)
    return str(value)


def _ts_plus_seconds(base_iso: str, seconds: int) -> str:
    """`YYYY-MM-DDTHH:MM:SSZ` + N초 — 같은 slug 의 outcome[i>0] 분리용."""
    from datetime import datetime, timedelta, timezone
    dt = datetime.strptime(base_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (dt + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def backfill_db(db_path: Path, cases: list[dict], *, rebuild: bool = False) -> tuple[int, int, int]:
    """frontmatter → case_runs row. (inserted, skipped_dup, warned) 반환.

    ts 는 *commit 시각* 우선 (`git log -1 --pretty=%cI --grep <slug>`) — frontmatter
    `date` 의 자정 폴백은 commit 없을 때만. 같은 slug 의 여러 outcome 은 +i초.

    `rebuild=True` 면 `case_runs` 전체 DELETE 후 재삽입 — 과거 자정 ts 정리용. 단
    case_log 가 박은 audit row 도 같이 사라짐 (frontmatter 가 없는 row 는 복구 X)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA)
    if rebuild:
        conn.execute("DELETE FROM case_runs")

    inserted = 0
    skipped = 0
    warned = 0

    for fm in cases:
        path: Path = fm["_path"]
        slug = fm.get("slug") or path.stem
        url = fm.get("url")
        date = str(fm.get("date") or "")
        if not date:
            print(f"WARN: {path.name} date 없음 — skip", file=sys.stderr)
            warned += 1
            continue
        status = str(fm.get("status") or "")
        outcomes = _classify_outcome(status, fm)
        if outcomes[0] == "error" and not status.startswith("❌"):
            print(f"WARN: {path.name} status='{status[:40]}' 알려진 패턴 X → 'error' 폴백 (사람 분류 필요)", file=sys.stderr)
            warned += 1

        failure_keys = fm.get("failure_keys")
        fk_json = json.dumps(failure_keys, ensure_ascii=False) if failure_keys else None
        fix_layer = _fmt_layer_str(fm.get("fix_layer"))

        files = []
        for k in ("engine_files_touched", "adapters_changed"):
            v = fm.get(k)
            if isinstance(v, list):
                files.extend(str(x) for x in v)
            elif v:
                files.append(str(v))
        files = sorted(set(files))
        files_json = json.dumps(files, ensure_ascii=False) if files else None

        text = path.read_text(encoding="utf-8").lstrip("﻿")
        reason = _extract_first_paragraph(text)
        commit_sha = _git_commit_for_slug(slug)
        commit_iso = _git_commit_iso_time_for_slug(slug)
        requested_by = fm.get("requested_by")

        base_ts = commit_iso or f"{date}T00:00:00Z"

        for i, outcome in enumerate(outcomes):
            ts = base_ts if i == 0 else _ts_plus_seconds(base_ts, i)
            try:
                conn.execute(
                    """INSERT INTO case_runs
                       (ts, slug, url, skill, outcome, failure_keys, fix_layer,
                        files_changed, case_md_slug, reason, requested_by, commit_sha)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        ts, slug, url, "hand-config", outcome, fk_json, fix_layer,
                        files_json, slug, reason, requested_by, commit_sha,
                    ),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                skipped += 1

    conn.commit()
    conn.close()
    return inserted, skipped, warned


def main() -> int:
    ap = argparse.ArgumentParser(description="docs/cases/*.md → docs/cases/INDEX.md")
    ap.add_argument("--cases-dir", type=Path, default=DEFAULT_CASES_DIR)
    ap.add_argument("--output", type=Path, default=None)
    ap.add_argument("--backfill-db", type=Path, default=None,
                    help="output/cases.sqlite3 같은 sqlite 경로 — frontmatter → case_runs row backfill")
    ap.add_argument("--rebuild", action="store_true",
                    help="--backfill-db 와 함께 — `case_runs` 전체 DELETE 후 재삽입. 과거 자정 ts 정리용. "
                         "case_log audit row 도 같이 사라짐 (frontmatter 없는 row 복구 X)")
    args = ap.parse_args()

    cases_dir: Path = args.cases_dir
    out_path: Path = args.output or (cases_dir / "INDEX.md")

    if not cases_dir.is_dir():
        print(f"cases 디렉토리 없음: {cases_dir}", file=sys.stderr)
        return 2

    paths = sorted(p for p in cases_dir.glob("*.md") if p.name != "INDEX.md" and not p.name.startswith("_"))
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

    if args.backfill_db:
        ins, dup, warn = backfill_db(args.backfill_db, cases, rebuild=args.rebuild)
        tag = "rebuild" if args.rebuild else "backfill"
        print(f"[{tag}] {args.backfill_db} — INSERT {ins} / dup {dup} / warn {warn}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
