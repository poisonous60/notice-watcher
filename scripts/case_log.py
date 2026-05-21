"""skill 실행 audit 로그 — `output/cases.sqlite3` 의 `case_runs` 테이블.

dev box only. N100 안 봄. `bot.sqlite3` 와 분리 (사용자 런타임 vs 개발 메타).

사용:
    # skill 마지막 단계 (commit push 직후):
    python scripts/case_log.py log \\
        --slug <slug> --skill hand-config \\
        --outcome <improved|handcrafted|no_change|rejected|rejected_with_policy|error> \\
        --reason "<1-3줄>" \\
        [--fix-layer <C+D>] [--failure-keys <key1,key2>] \\
        [--case-md-slug <slug>] [--files-changed <p1,p2>]

    # agent retrospect (P4 deferred — 지금은 직접 호출 가능):
    python scripts/case_log.py query [--slug X] [--host H] [--failure-key K] \\
                                     [--file-touched PREFIX] [--layer L] \\
                                     [--requested-by USER] [--recent N] \\
                                     [--limit 20] [--format table|json]

설계 메모: `docs/case_runs DB 계획.md` rev 2 (β minimal — begin/end 폐기, 단일 commit 정책).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # bot/ 패키지 import 위해

from bot.case_runs_meta import OUTCOMES, SCHEMA, escape_like  # noqa: E402

DB_PATH = ROOT / "output" / "cases.sqlite3"


def _ensure_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _git(*args: str) -> Optional[str]:
    try:
        r = subprocess.run(
            ["git", *args],
            cwd=str(ROOT),
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return None
        return r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _now_iso_z() -> str:
    """ms 정밀도 포함 ISO8601 — 같은 초 두 호출 시 UNIQUE 충돌 회피."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _derive_commit_sha() -> Optional[str]:
    return _git("rev-parse", "HEAD")


def _derive_files_changed() -> Optional[list[str]]:
    """마지막 1 commit 의 변경 파일. 단일 commit 정책 — skill 한 번 = 한 commit 권장."""
    out = _git("diff", "--name-only", "HEAD~1..HEAD")
    if out is None:
        return None  # git 명령 실패 — NULL 박음
    files = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return files  # 변경 없는 commit 도 있을 수 있음 — 빈 list 박음


def _has_uncommitted_changes() -> bool:
    """staged + working tree 에 변경 있나 — `case_log log` 가 commit 전 호출됐는지 검출."""
    out = _git("status", "--porcelain")
    return bool(out and out.strip())


def _lookup_url_and_requester(slug: str) -> tuple[Optional[str], Optional[str]]:
    """FAILED.json / 성공 후 .json / triage_queue.jsonl 에서 slug 매칭하는 url + requested_by lookup.

    hand-config 성공 후엔 FAILED.json 이 사라지므로 같은 디렉터리의 `<slug>.json`
    (정상 poll_state) 도 폴백으로 살핀다 — 그래야 후속 `case_log save` 가 url NULL 로
    들어가지 않는다 (Cases 대시보드 ↗ 링크 비활성 회피).
    """
    url, requester = None, None

    poll_dir = ROOT / "output" / "poll_state"
    for fname in (f"{slug}.FAILED.json", f"{slug}.json"):
        cand = poll_dir / fname
        if cand.exists():
            try:
                d = json.loads(cand.read_text(encoding="utf-8"))
                url = d.get("url") or url
                if url:
                    break
            except (OSError, json.JSONDecodeError):
                pass

    triage = ROOT / "output" / "triage_queue.jsonl"
    if triage.exists():
        try:
            with triage.open("r", encoding="utf-8") as fh:  # line-by-line iter (큰 파일 메모리 절약)
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if d.get("slug") != slug:
                        continue
                    # 마지막 매칭 항목 우선 (덮어쓰기)
                    url = d.get("url") or url
                    rb = d.get("requested_by")
                    if isinstance(rb, dict):
                        requester = rb.get("name") or rb.get("id") or requester
                    elif isinstance(rb, str):
                        requester = rb or requester
        except OSError:
            pass

    return url, requester


def _split_csv(s: Optional[str]) -> Optional[list[str]]:
    if s is None:
        return None
    parts = [p.strip() for p in s.split(",") if p.strip()]
    return parts or None


def cmd_log(args: argparse.Namespace) -> int:
    outcome = args.outcome
    if outcome not in OUTCOMES:
        print(f"WARN: outcome '{outcome}' unknown — 'error' 폴백. 알려진 값: {OUTCOMES}", file=sys.stderr)
        outcome = "error"

    ts = _now_iso_z()
    failure_keys = _split_csv(args.failure_keys)
    files_arg = _split_csv(args.files_changed)
    files_changed = files_arg if files_arg is not None else _derive_files_changed()
    commit_sha = _derive_commit_sha()
    if files_arg is None and _has_uncommitted_changes():
        # commit 전 호출 — derive 가 직전 commit 의 sha+diff 잡음 (현 case 아님).
        # SKILL.md §5 step 7 = commit + push 뒤에 호출하도록 명시. graceful 진행.
        print(
            "⚠ staged/working tree 변경 있음 — case_log 가 직전 commit 의 sha/files 를 잡습니다.\n"
            "  SKILL.md §5 step 7 따라 'git commit && git push' 후 호출 권장.\n"
            "  (`--files-changed` 명시 override 하면 이 경고 안 뜸.)",
            file=sys.stderr,
        )
    url, requester = _lookup_url_and_requester(args.slug)
    if args.requested_by:  # CLI override
        requester = args.requested_by
    # case .md 는 관례상 docs/cases/<slug>.md → 미지정 시 slug 로 기본 (dashboard /cases md 링크가
    # case_md_slug 컬럼으로 .md 를 찾음 — null 이면 md 안 보임). 다른 .md 명이면 --case-md-slug 명시.
    case_md_slug = args.case_md_slug or args.slug

    conn = _ensure_db()
    try:
        conn.execute(
            """INSERT INTO case_runs
               (ts, slug, url, skill, outcome, failure_keys, fix_layer,
                files_changed, case_md_slug, reason, requested_by, commit_sha)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ts, args.slug, url, args.skill, outcome,
                json.dumps(failure_keys, ensure_ascii=False) if failure_keys else None,
                args.fix_layer,
                json.dumps(files_changed, ensure_ascii=False) if files_changed is not None else None,
                case_md_slug,
                args.reason,
                requester,
                commit_sha,
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError as e:
        print(f"FAIL: INSERT 충돌 — {e} (같은 slug+ts row 이미 있음)", file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(f"[case_log] OK row 박음 — slug={args.slug} skill={args.skill} outcome={outcome} ts={ts}")
    if commit_sha:
        print(f"           commit={commit_sha[:12]} files={len(files_changed) if files_changed else 0}")
    return 0


def _query_sql(args: argparse.Namespace) -> tuple[str, list[Any]]:
    """LIKE 패턴은 escape_like 로 사용자 input 의 `_`/`%` wildcard 화 차단 + ESCAPE '\\\\'."""
    sql = "SELECT * FROM case_runs WHERE 1=1"
    params: list[Any] = []
    if args.slug:
        sql += " AND slug = ?"
        params.append(args.slug)
    if args.host:
        h = escape_like(args.host)
        sql += " AND (slug LIKE ? ESCAPE '\\' OR url LIKE ? ESCAPE '\\')"
        params.append(f"%{h}%")
        params.append(f"%{h}%")
    if args.failure_key:
        # JSON array 안 정확 키 매칭 (substring 충돌 회피)
        k = escape_like(args.failure_key)
        sql += " AND failure_keys LIKE ? ESCAPE '\\'"
        params.append(f'%"{k}"%')
    if args.file_touched:
        ft = escape_like(args.file_touched)
        sql += " AND files_changed LIKE ? ESCAPE '\\'"
        params.append(f"%{ft}%")
    if args.layer:
        ly = escape_like(args.layer)
        sql += " AND fix_layer LIKE ? ESCAPE '\\'"
        params.append(f"%{ly}%")
    if args.requested_by:
        sql += " AND requested_by = ?"
        params.append(args.requested_by)
    if args.recent is not None:
        # --recent 0 = "오늘 안" (24h) 의미. None = 시간 필터 없음.
        sql += f" AND ts > datetime('now', '-{int(args.recent)} days')"
    sql += " ORDER BY ts DESC LIMIT ?"
    params.append(int(args.limit))
    return sql, params


def cmd_query(args: argparse.Namespace) -> int:
    if not DB_PATH.exists():
        print(f"DB 없음: {DB_PATH}. backfill 또는 첫 log 호출 후 재시도.", file=sys.stderr)
        return 0  # skill 안 깨지게 0 폴백
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        sql, params = _query_sql(args)
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    if args.format == "json":
        out = []
        for r in rows:
            d = dict(r)
            for jcol in ("failure_keys", "files_changed"):
                if d.get(jcol):
                    try:
                        d[jcol] = json.loads(d[jcol])
                    except (TypeError, json.JSONDecodeError):
                        pass
            out.append(d)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    # table format
    if not rows:
        print("(0 rows)")
        return 0
    header = f"{'slug':<48} {'ts':<20} {'outcome':<22} {'layer':<8} {'failure_keys':<24} {'reason':<50} case_md"
    print(header)
    print("-" * len(header))
    for r in rows:
        slug = (r["slug"] or "")[:46]
        ts = (r["ts"] or "")[:19]
        out = (r["outcome"] or "")[:20]
        layer = (r["fix_layer"] or "")[:6]
        keys = (r["failure_keys"] or "")[:22]
        reason = ((r["reason"] or "").replace("\n", " "))[:48]
        case_md = (r["case_md_slug"] or "")
        print(f"{slug:<48} {ts:<20} {out:<22} {layer:<8} {keys:<24} {reason:<50} {case_md}")
    print(f"({len(rows)} rows)")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="skill 실행 audit 로그 — case_runs")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("log", help="row 1개 박기 (skill 마지막 단계)")
    pl.add_argument("--slug", required=True)
    pl.add_argument("--skill", required=True)
    pl.add_argument("--outcome", required=True,
                    help=f"{'|'.join(OUTCOMES)} (unknown → error 폴백)")
    pl.add_argument("--reason", required=True)
    pl.add_argument("--fix-layer", default=None)
    pl.add_argument("--failure-keys", default=None, help="콤마 구분")
    pl.add_argument("--case-md-slug", default=None)
    pl.add_argument("--files-changed", default=None,
                    help="콤마 구분 — 보통 git diff 자동, override 시만")
    pl.add_argument("--requested-by", default=None,
                    help="보통 triage_queue/FAILED.json 자동, override 시만")
    pl.set_defaults(func=cmd_log)

    pq = sub.add_parser("query", help="row 검색 (agent retrospect)")
    pq.add_argument("--slug", default=None)
    pq.add_argument("--host", default=None, help="slug/url substring 매칭")
    pq.add_argument("--failure-key", default=None)
    pq.add_argument("--file-touched", default=None, help="files_changed substring")
    pq.add_argument("--layer", default=None)
    pq.add_argument("--requested-by", default=None)
    pq.add_argument("--recent", type=int, default=None, help="최근 N 일")
    pq.add_argument("--limit", type=int, default=20)
    pq.add_argument("--format", choices=["table", "json"], default="table")
    pq.set_defaults(func=cmd_query)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
