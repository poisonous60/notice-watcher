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

    python scripts/cases_index.py query --failure-key <key>     # 같은 failure_key 누적 case
    python scripts/cases_index.py query --signal "<regex>"      # case .md 본문 grep
    python scripts/cases_index.py query --fix-layer <L>         # 같은 fix_layer
    python scripts/cases_index.py query --deferred              # _deferred_heuristics.md trigger 매칭
    python scripts/cases_index.py query --vocab-candidate <name> # 같은 vocab_candidates 후보 가진 case
    SKILL hand-config §6.2 강제 게이트 — 매 case 처리 §2 진입 전에 진단한 failure_keys 마다 호출.
    누적 ≥3 면 트랙 B 자동 진입 (deferred 보류 불가).

    python scripts/cases_index.py vocab-trigger                 # vocab_candidates 임계 체크 + alert history 적재
    SKILL hand-config §5 commit 후 호출 — output/vocab_alerts.json 에 누적 + 임계 도달 시 출력.
    ADR 0003 의 임계 룰 (high≥1 + total≥N, 또는 med≥N) 적용. low only = 보류. 모순 (high+low 공존) 검출.

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


def _read_all_cases(cases_dir: Path) -> list[dict]:
    paths = sorted(p for p in cases_dir.glob("*.md") if p.name != "INDEX.md" and not p.name.startswith("_"))
    out: list[dict] = []
    for p in paths:
        c = parse_case(p)
        if c is not None:
            out.append(c)
    return out


def _case_summary_line(fm: dict) -> str:
    slug = fm.get("slug") or fm["_path"].stem
    date = str(fm.get("date") or "????-??-??")
    outcome = fm.get("outcome") or "(미기재)"
    layer = _fmt_layer(fm.get("fix_layer")) or "none"
    return f"  - {slug}  {date}  {outcome}  fix_layer={layer}"


def run_query(argv: list[str]) -> int:
    qp = argparse.ArgumentParser(
        prog="cases_index.py query",
        description="SKILL hand-config §6.2 cross-case lookup. 누적 ≥3 면 트랙 B 자동 진입.",
    )
    qp.add_argument("--cases-dir", type=Path, default=DEFAULT_CASES_DIR)
    qp.add_argument("--failure-key", action="append", default=[],
                    help="failure_keys 안에 이 키가 있는 case (반복 OK = OR)")
    qp.add_argument("--signal", action="append", default=[],
                    help="case .md 본문에 매칭되는 regex (반복 OK = OR, multi-line, case-insensitive)")
    qp.add_argument("--fix-layer", action="append", default=[],
                    help="fix_layer 가 이 값 (반복 OK = OR)")
    qp.add_argument("--status-emoji", default=None,
                    help="status 가 이 이모지로 시작하는 case (예: 🔧/✅/🚫/❌)")
    qp.add_argument("--deferred", action="store_true",
                    help="docs/cases/_deferred_heuristics.md trigger 줄과 케이스 매칭")
    qp.add_argument("--vocab-candidate", action="append", default=[],
                    help="vocab_candidates 안에 이 candidate 가 있는 case (반복 OK = OR). ADR 0003.")
    qp.add_argument("--json", action="store_true",
                    help="기계 가독 JSON 출력 (skill 자동 게이트용)")
    args = qp.parse_args(argv)

    cases_dir: Path = args.cases_dir
    if not cases_dir.is_dir():
        print(f"cases 디렉토리 없음: {cases_dir}", file=sys.stderr)
        return 2

    all_cases = _read_all_cases(cases_dir)
    results: dict[str, list[dict]] = {}

    for fk in args.failure_key:
        matched = [c for c in all_cases if fk in (c.get("failure_keys") or [])]
        results[f"failure_key={fk}"] = matched

    for sig in args.signal:
        pat = re.compile(sig, re.I | re.M)
        matched = [c for c in all_cases if pat.search(c["_path"].read_text(encoding="utf-8"))]
        results[f"signal={sig}"] = matched

    for fl in args.fix_layer:
        matched: list[dict] = []
        for c in all_cases:
            v = c.get("fix_layer")
            if v is None:
                continue
            vs = [str(x) for x in (v if isinstance(v, (list, tuple)) else [v])]
            if fl in vs:
                matched.append(c)
        results[f"fix_layer={fl}"] = matched

    if args.status_emoji:
        em = args.status_emoji
        matched = [c for c in all_cases if str(c.get("status") or "").startswith(em)]
        results[f"status_emoji={em}"] = matched

    for vc in args.vocab_candidate:
        matched = []
        for c in all_cases:
            vlist = c.get("vocab_candidates") or []
            if not isinstance(vlist, list):
                continue
            for item in vlist:
                if isinstance(item, dict) and item.get("candidate") == vc:
                    matched.append(c)
                    break
        results[f"vocab_candidate={vc}"] = matched

    if args.deferred:
        deferred_path = cases_dir / "_deferred_heuristics.md"
        if not deferred_path.exists():
            print(f"_deferred_heuristics.md 없음: {deferred_path}", file=sys.stderr)
        else:
            text = deferred_path.read_text(encoding="utf-8")
            # 후보 한 줄 형식: `- **<name>** — <신호> — <잡힐 case> — <사유> — <트리거> — commit ...`
            for line in text.splitlines():
                m = re.match(r"-\s+\*\*`?([^`*]+)`?\*\*\s+—\s+(.+)$", line.strip())
                if not m:
                    continue
                name = m.group(1).strip()
                rest = m.group(2)
                # signal 부분만 자유 추출 — 본문 grep 으로 매칭 위해 첫 두 segment 만 사용
                segs = [s.strip() for s in rest.split("—")]
                signal = segs[0] if segs else ""
                # 본문에 후보 이름 또는 첫 키워드 grep
                key_tokens = re.findall(r"`([^`]+)`", line) + [name]
                matched = []
                for c in all_cases:
                    body = c["_path"].read_text(encoding="utf-8")
                    if any(tok in body for tok in key_tokens if len(tok) > 3):
                        matched.append(c)
                results[f"deferred:{name}"] = matched

    if not results:
        print("질의 항목 없음 — --failure-key/--signal/--fix-layer/--status-emoji/--deferred 중 1개 필요.", file=sys.stderr)
        return 2

    if args.json:
        out = {
            label: {
                "count": len(matches),
                "slugs": [c.get("slug") or c["_path"].stem for c in matches],
                "track_b_trigger": len(matches) >= 3,
            }
            for label, matches in results.items()
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    for label, matches in results.items():
        n = len(matches)
        trigger = " ⚠ 트랙 B 진입 (N≥3)" if n >= 3 else ""
        print(f"\n[query] {label} → {n}건{trigger}")
        for c in sorted(matches, key=lambda x: str(x.get("date") or ""), reverse=True):
            print(_case_summary_line(c))
            keys = c.get("failure_keys")
            if keys:
                print(f"    keys: {_fmt_list(keys)}")
    print()
    return 0


def cmd_vocab_trigger(argv: list[str]) -> int:
    """vocab_candidates 임계 체크 + alert history 적재 (ADR 0003).

    case .md frontmatter 의 vocab_candidates (deferred=true 항목) 모아 후보별 카운트.
    임계 룰: high≥1 + total≥N = 진입 권장 / med≥N = 진입 권장 / low only = 보류.
    cross-evidence 모순: 같은 candidate 의 case 들이 confidence high+low 공존 = 알림.
    output/vocab_alerts.json 에 history 누적 (gitignore). 매 호출 = noise pressure ↑.
    """
    ap = argparse.ArgumentParser(prog="cases_index.py vocab-trigger")
    ap.add_argument("--cases-dir", type=Path, default=DEFAULT_CASES_DIR)
    ap.add_argument("--alert-file", type=Path,
                    default=ROOT / "output" / "vocab_alerts.json",
                    help="누적 alert history 파일 (gitignore)")
    ap.add_argument("--threshold", type=int, default=3,
                    help="임계 N (deferred_heuristics 와 동일)")
    ap.add_argument("--json", action="store_true",
                    help="기계 가독 JSON 출력")
    ap.add_argument("--no-write", action="store_true",
                    help="alert history 적재 안 함 (dry-run)")
    ap.add_argument("--silent-if-empty", action="store_true",
                    help="vocab_candidates 후보 0건 + 임계 미달 시 출력 X (hand-config §5 step 10 호출용)")
    args = ap.parse_args(argv)

    cases_dir: Path = args.cases_dir
    if not cases_dir.is_dir():
        print(f"cases 디렉토리 없음: {cases_dir}", file=sys.stderr)
        return 2

    all_cases = _read_all_cases(cases_dir)

    # candidate → entries (slug, confidence, deferred, vocab_attempt_failed)
    by_candidate: dict[str, list[dict]] = {}
    for c in all_cases:
        vlist = c.get("vocab_candidates") or []
        if not isinstance(vlist, list):
            continue
        slug = c.get("slug") or c["_path"].stem
        for item in vlist:
            if not isinstance(item, dict):
                continue
            name = item.get("candidate")
            if not name:
                continue
            # failure feedback: vocab_attempt_failed=True 면 confidence 자동 강등 1단계
            raw_conf = str(item.get("confidence", "unknown")).lower()
            failed = bool(item.get("vocab_attempt_failed"))
            conf = raw_conf
            if failed:
                conf = {"high": "med", "med": "low", "low": "low"}.get(raw_conf, "low")
            by_candidate.setdefault(name, []).append({
                "slug": slug,
                "confidence": conf,
                "raw_confidence": raw_conf,
                "deferred": bool(item.get("deferred")),
                "vocab_attempt_failed": failed,
                "analysis_date": item.get("analysis_date"),
            })

    # 임계 룰 + 모순 검출
    triggered: list[dict] = []
    contradictions: list[dict] = []
    sub_threshold: list[dict] = []
    for name, entries in sorted(by_candidate.items()):
        deferred_entries = [e for e in entries if e["deferred"]]
        n = len(deferred_entries)
        cnt = Counter(e["confidence"] for e in deferred_entries)
        n_high = cnt.get("high", 0)
        n_med = cnt.get("med", 0)
        n_low = cnt.get("low", 0)

        reason: str | None = None
        if n_high >= 1 and n >= args.threshold:
            reason = f"high>=1 + total={n}>={args.threshold}"
        elif n_med >= args.threshold:
            reason = f"med>={args.threshold}"
        # low only = 보류 (의무 재평가 강제)

        entry = {
            "candidate": name,
            "count": n,
            "confidences": dict(cnt),
            "reason": reason,
            "cases": [e["slug"] for e in deferred_entries],
        }
        if reason:
            triggered.append(entry)
        elif n > 0:
            sub_threshold.append(entry)

        # 모순 — high + low 공존 (deferred 무관, 전체 case 보고 판단)
        all_conf_cnt = Counter(e["confidence"] for e in entries)
        if all_conf_cnt.get("high", 0) >= 1 and all_conf_cnt.get("low", 0) >= 1:
            contradictions.append({
                "candidate": name,
                "confidences": dict(all_conf_cnt),
                "cases": [(e["slug"], e["confidence"]) for e in entries],
            })

    # alert history 적재 — 후보별 keyed (candidate → first_seen/last_seen/count/last_trigger_count)
    alert_history: dict = {"first_alert_at": None, "candidates": {}}
    if args.alert_file.exists():
        try:
            loaded = json.loads(args.alert_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                alert_history = loaded
                alert_history.setdefault("candidates", {})
                alert_history.setdefault("first_alert_at", None)
                # legacy migration — 옛 `alerts: [...]` 구조면 candidates 로 옮김
                if "alerts" in alert_history and isinstance(alert_history["alerts"], list):
                    for old in alert_history["alerts"]:
                        for cname in (old.get("triggered") or []):
                            slot = alert_history["candidates"].setdefault(cname, {
                                "first_seen_at": old.get("first_seen_at"),
                                "last_seen_at": old.get("last_seen_at"),
                                "alert_count": 0,
                                "last_trigger_count": None,
                            })
                            slot["alert_count"] = int(slot.get("alert_count", 0)) + int(old.get("count", 1))
                            if not slot.get("first_seen_at"):
                                slot["first_seen_at"] = old.get("first_seen_at")
                            slot["last_seen_at"] = old.get("last_seen_at") or slot.get("last_seen_at")
                    del alert_history["alerts"]
        except json.JSONDecodeError:
            pass

    now_iso = datetime.now(timezone.utc).isoformat()
    if triggered and not args.no_write:
        args.alert_file.parent.mkdir(parents=True, exist_ok=True)
        for t in triggered:
            cname = t["candidate"]
            slot = alert_history["candidates"].setdefault(cname, {
                "first_seen_at": now_iso,
                "last_seen_at": now_iso,
                "alert_count": 0,
                "last_trigger_count": None,
            })
            slot["last_seen_at"] = now_iso
            slot["alert_count"] = int(slot.get("alert_count", 0)) + 1
            slot["last_trigger_count"] = int(t["count"])
        if alert_history["first_alert_at"] is None:
            alert_history["first_alert_at"] = now_iso
        args.alert_file.write_text(
            json.dumps(alert_history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # 누적 = 후보별 alert_count 합산
    total_alerts = sum(int(slot.get("alert_count", 0))
                       for slot in alert_history.get("candidates", {}).values())

    if args.json:
        out = {
            "triggered": triggered,
            "sub_threshold": sub_threshold,
            "contradictions": contradictions,
            "total_alert_count": total_alerts,
            "threshold": args.threshold,
            "candidates_total": len(by_candidate),
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    # 모순 = silent 무시하고 항상 출력 (캐시 오염 의심 신호 — 침묵 X)
    contradiction_block = ""
    if contradictions:
        lines = ["[모순] vocab_candidates cross-evidence 모순 (high+low 공존):"]
        for c in contradictions:
            confs = "/".join(f"{k}:{v}" for k, v in sorted(c["confidences"].items()))
            lines.append(f"  - {c['candidate']}: {confs}")
        contradiction_block = "\n".join(lines)

    if not by_candidate:
        if args.silent_if_empty:
            if contradiction_block:
                print(contradiction_block)
            return 0
        print("[vocab-trigger] vocab_candidates 후보 0건 — backfill 권장 (ADR 0003 §Consequences)")
        if contradiction_block:
            print(contradiction_block)
        return 0

    if triggered:
        print("[알림] vocab_candidates 임계 도달:")
        for t in triggered:
            confs = "/".join(f"{k}:{v}" for k, v in sorted(t["confidences"].items()))
            preview = ", ".join(t["cases"][:3])
            if len(t["cases"]) > 3:
                preview += f", +{len(t['cases'])-3}"
            print(f"  - {t['candidate']} = {t['count']}건 ({confs}) — {t['reason']} — cases: {preview}")
        print(f"  알림 누적 {total_alerts}회 — /vocabulary-extension 호출 권장")
    else:
        if args.silent_if_empty:
            if contradiction_block:
                print(contradiction_block)
            return 0
        print(f"[vocab-trigger] 임계 미달 ({len(by_candidate)} 후보 — threshold={args.threshold})")
        for s in sub_threshold:
            confs = "/".join(f"{k}:{v}" for k, v in sorted(s["confidences"].items()))
            print(f"  - {s['candidate']} = {s['count']}건 ({confs})")

    if contradiction_block:
        print(contradiction_block)

    return 0


def main() -> int:
    # query / vocab-trigger sub-command — sys.argv[1] 검사 (argparse subparser 안 흔드는 쪽)
    if len(sys.argv) > 1 and sys.argv[1] == "query":
        return run_query(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "vocab-trigger":
        return cmd_vocab_trigger(sys.argv[2:])

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
