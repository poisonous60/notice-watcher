"""사이트 카탈로그 일괄 등록 driver.

`configs/candidates/catalog.yaml` 의 entries 를 읽어 각 board URL 마다
`scripts/register.py <url>` 를 직렬 호출한다. 결과는
`output/register_batch_runs.sqlite3` 에 누적 — dashboard `/candidates` 에서
카테고리 × tier × 결과 분포로 표시.

설계: `docs/사이트 카탈로그 자동 등록 파이프라인 계획.md`.

사용:
    python scripts/register_batch.py --dry-run                    # 현재 카탈로그 vs 등록 상태만 표시
    python scripts/register_batch.py --tier=A,B --limit=10        # tier A/B 중 미시도 10개
    python scripts/register_batch.py --category=kr-game-official  # 한 카테고리만
    python scripts/register_batch.py --cooldown-days=7            # 7일 안에 실패한 건 skip

flags:
    --catalog PATH        catalog.yaml 경로 (기본 configs/candidates/catalog.yaml)
    --category CSV        category enum 필터 (콤마구분 가능)
    --tier CSV            tier A~G 필터
    --provenance CSV      doc | history | web 필터
    --limit N             처리 entry 수 상한
    --max-attempts N      register.py 의 --max-attempts (기본 4)
    --cooldown-days N     같은 slug 의 .FAILED 가 N 일 이내면 skip (기본 7)
    --timeout SEC         register.py 1회 호출 timeout (기본 900 = 15분)
    --dry-run             실제 register 안 돌리고 skip 판단만
    --force               이미 registered/rejected/failed 라도 다시 시도 (idempotency 우회)

rc:
    0  정상 종료 (등록 성공 여부 무관)
    2  catalog 로드 실패 / 검증 실패
    3  --catalog 경로 없음
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    print("PyYAML 필요: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# register.py 가 호출한 trace 가 dev box `output/traces/` 에 박히도록 — dashboard
# `/timings?source=local` 에서 봇 production 과 별도로 본다. 사용자가 명시적으로
# `TRACE_ENABLED=0` 박은 경우만 비활성화.
os.environ.setdefault("TRACE_ENABLED", "1")

from probe.paths import url_to_slug  # noqa: E402

CATALOG_DEFAULT = ROOT / "configs" / "candidates" / "catalog.yaml"
CONFIGS_DIR = ROOT / "configs"
CONFIGS_SNAPSHOT = ROOT / "configs.snapshot"
STATE_DIR = ROOT / "output" / "poll_state"
SNAPSHOT_STATE_DIR = ROOT / "output" / "snapshot" / "poll_state"
TRIAGE_LATER = ROOT / "output" / "triage_later.json"
RUNS_DB = ROOT / "output" / "register_batch_runs.sqlite3"
REGISTER_PY = ROOT / "scripts" / "register.py"

# Plan §3a enum
ALLOWED_CATEGORIES = {
    "global-game-store", "global-game-official", "kr-game-official",
    "global-community", "forum-engine", "kr-community-open",
    "kr-community-blocked", "kr-community-login", "social-media", "news-wiki",
}
ALLOWED_TIERS = {"A", "B", "C", "D", "E", "F", "G"}
ALLOWED_STRATEGIES = {
    "rss", "httpx_json", "httpx_html", "playwright_html", "handwritten", "unknown",
}
ALLOWED_PROVENANCE = {"doc", "history", "web"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Catalog load + validate
# --------------------------------------------------------------------------- #
def load_catalog(path: Path) -> list[dict]:
    """yaml 읽어 entries 리스트 반환. 스키마 위반 시 ValueError."""
    if not path.exists():
        raise FileNotFoundError(f"catalog 경로 없음: {path}")
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ValueError(f"catalog YAML 파싱 실패: {e}") from e
    if not isinstance(doc, dict):
        raise ValueError("catalog 루트가 mapping 아님")
    entries = doc.get("entries")
    if not isinstance(entries, list):
        raise ValueError("`entries` 가 list 가 아님")
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for i, e in enumerate(entries):
        ctx = f"entries[{i}]"
        if not isinstance(e, dict):
            raise ValueError(f"{ctx}: mapping 아님")
        for k in ("id", "name", "category", "tier", "expected_strategy", "boards", "source"):
            if k not in e:
                raise ValueError(f"{ctx}: 필드 '{k}' 누락")
        eid = e["id"]
        if not isinstance(eid, str) or not eid:
            raise ValueError(f"{ctx}: id 비어있음")
        if eid in seen_ids:
            raise ValueError(f"{ctx}: id 중복 '{eid}'")
        seen_ids.add(eid)
        if e["category"] not in ALLOWED_CATEGORIES:
            raise ValueError(f"{ctx}({eid}): category '{e['category']}' 가 enum 밖")
        if e["tier"] not in ALLOWED_TIERS:
            raise ValueError(f"{ctx}({eid}): tier '{e['tier']}' 가 enum 밖")
        if e["expected_strategy"] not in ALLOWED_STRATEGIES:
            raise ValueError(f"{ctx}({eid}): expected_strategy '{e['expected_strategy']}' 가 enum 밖")
        boards = e["boards"]
        if not isinstance(boards, list) or not boards:
            raise ValueError(f"{ctx}({eid}): boards 비어있음")
        for j, b in enumerate(boards):
            if not isinstance(b, dict) or "url" not in b:
                raise ValueError(f"{ctx}({eid}).boards[{j}]: url 없음")
            url = b["url"]
            if not isinstance(url, str) or not (url.startswith("http://") or url.startswith("https://")):
                raise ValueError(f"{ctx}({eid}).boards[{j}]: url 이 http(s) 가 아님: {url!r}")
            if url in seen_urls:
                raise ValueError(f"{ctx}({eid}).boards[{j}]: url 중복 '{url}'")
            seen_urls.add(url)
        src = e["source"]
        if not isinstance(src, dict):
            raise ValueError(f"{ctx}({eid}): source mapping 아님")
        prov = src.get("provenance")
        if prov not in ALLOWED_PROVENANCE:
            raise ValueError(f"{ctx}({eid}): source.provenance '{prov}' 가 enum 밖")
    return entries


# --------------------------------------------------------------------------- #
# Idempotency
# --------------------------------------------------------------------------- #
def _load_triage_later() -> set[str]:
    if not TRIAGE_LATER.exists():
        return set()
    try:
        d = json.loads(TRIAGE_LATER.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {str(s) for s in (d.get("later") or []) if s}


def _is_already_registered(slug: str) -> bool:
    """dev box configs/ 또는 N100 snapshot configs.snapshot/ 에 config 존재.

    plan §5: codex review #1 의 BLOCKER "N100 가 dev 보다 앞서 register 가능" 반영.
    """
    return ((CONFIGS_DIR / f"{slug}.json").exists()
            or (CONFIGS_SNAPSHOT / f"{slug}.json").exists())


def _is_already_rejected(slug: str) -> bool:
    return ((STATE_DIR / f"{slug}.REJECTED.json").exists()
            or (SNAPSHOT_STATE_DIR / f"{slug}.REJECTED.json").exists())


def _is_bug_marked(slug: str) -> bool:
    """`.BUG.json` 마커 — 코드 버그/시스템 결함으로 막힌 slug. register.py 가 박음.
    재시도 X (`scripts/register.py:_save_bug`).
    """
    return ((STATE_DIR / f"{slug}.BUG.json").exists()
            or (SNAPSHOT_STATE_DIR / f"{slug}.BUG.json").exists())


def _failed_age_days(slug: str) -> Optional[float]:
    """가장 최신의 .FAILED.json 의 age(일). 없으면 None."""
    candidates = [
        STATE_DIR / f"{slug}.FAILED.json",
        SNAPSHOT_STATE_DIR / f"{slug}.FAILED.json",
    ]
    newest = None
    for p in candidates:
        if not p.exists():
            continue
        m = p.stat().st_mtime
        if newest is None or m > newest:
            newest = m
    if newest is None:
        return None
    return (time.time() - newest) / 86400.0


# --------------------------------------------------------------------------- #
# Outcome classification
# --------------------------------------------------------------------------- #
# rc → status. Codex review #1 반영 (plan §5 step 5).
RC_STATUS = {
    0: "registered",          # 단, configs/<slug>.json 확인 후 결정
    1: "failed",               # generation 실패. `.FAILED.json` 동반 보통.
    2: "policy_rejected",      # BLOCKED/LOGIN. argparse error 도 2 — stderr 검사로 구분.
    3: "gate_rejected",        # recognize_reject / single-article / multi_host_hub 등
    4: "error_cli",            # --unlearn/--clear-bug invalid (batch 는 안 씀)
    6: "error_unexpected",     # --gate-only no-match (batch 는 안 씀)
    7: "error_unexpected",     # --gate-only no-probe (batch 는 안 씀)
}


def classify_outcome(slug: str, rc: int, stderr: str) -> tuple[str, str]:
    """(status, reason) 매핑. plan §5 step 5.

    rc=2 가 argparse error (stderr 가 'usage:' 로 시작) 면 error_cli 로 분기.
    rc=0 이지만 config 부재면 error_no_config (안전망).
    timeout 시 rc 는 None 또는 -1 — 호출자가 'timeout' 으로 박음.
    """
    cfg_path = CONFIGS_DIR / f"{slug}.json"
    if rc == 0:
        if cfg_path.exists():
            return "registered", "ok"
        return "error_no_config", "rc=0 이지만 config 부재 — register.py 안에서 path 오류 가능"
    if rc == 2:
        first = (stderr or "").lstrip().split("\n", 1)[0].lower()
        if first.startswith("usage:"):
            return "error_cli", "argparse error: " + first[:200]
        return "policy_rejected", "BLOCKED/LOGIN — register.py policy_check 거부"
    if rc in RC_STATUS:
        return RC_STATUS[rc], f"rc={rc}"
    return "error_runtime", f"unexpected rc={rc}"


def read_actual_strategy(slug: str) -> tuple[Optional[str], Optional[str]]:
    """등록된 config 의 strategy + adapter 추출. plan §5 step 6.

    codex review #1: recognizer fast-path 도 written config 만 보면 됨.
    """
    p = CONFIGS_DIR / f"{slug}.json"
    if not p.exists():
        return None, None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None
    return d.get("strategy"), d.get("adapter")


# --------------------------------------------------------------------------- #
# Runs DB
# --------------------------------------------------------------------------- #
RUNS_DDL = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    cand_id TEXT NOT NULL,
    url TEXT NOT NULL,
    slug TEXT NOT NULL,
    category TEXT NOT NULL,
    tier TEXT NOT NULL,
    expected_strategy TEXT NOT NULL,
    actual_strategy TEXT,
    actual_adapter TEXT,
    rc INTEGER,
    status TEXT NOT NULL,
    reason TEXT,
    duration_s REAL,
    stderr_tail TEXT
);
CREATE INDEX IF NOT EXISTS runs_cand_id_ts ON runs(cand_id, ts DESC);
CREATE INDEX IF NOT EXISTS runs_slug_ts ON runs(slug, ts DESC);
CREATE INDEX IF NOT EXISTS runs_status ON runs(status);
"""


def open_runs_db() -> sqlite3.Connection:
    RUNS_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(RUNS_DB), timeout=15.0)
    conn.executescript(RUNS_DDL)
    return conn


def insert_run(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        """INSERT INTO runs (ts, cand_id, url, slug, category, tier,
            expected_strategy, actual_strategy, actual_adapter,
            rc, status, reason, duration_s, stderr_tail)
           VALUES (:ts, :cand_id, :url, :slug, :category, :tier,
                   :expected_strategy, :actual_strategy, :actual_adapter,
                   :rc, :status, :reason, :duration_s, :stderr_tail)""",
        row,
    )
    conn.commit()


# --------------------------------------------------------------------------- #
# Per-board run
# --------------------------------------------------------------------------- #
def run_one(entry: dict, board: dict, args, conn: sqlite3.Connection) -> dict:
    """1 board 실행. dict 반환 — caller 가 progress print 용."""
    cand_id = entry["id"]
    url = board["url"]
    slug = url_to_slug(url)
    base_row = {
        "ts": _now_iso(),
        "cand_id": cand_id,
        "url": url,
        "slug": slug,
        "category": entry["category"],
        "tier": entry["tier"],
        "expected_strategy": entry["expected_strategy"],
        "actual_strategy": None,
        "actual_adapter": None,
        "rc": None,
        "status": "",
        "reason": "",
        "duration_s": None,
        "stderr_tail": None,
    }

    # idempotency (codex review #1: snapshot 도 본다)
    if not args.force:
        if _is_already_registered(slug):
            base_row["status"] = "already_registered"
            base_row["reason"] = "configs/<slug>.json 또는 snapshot 존재"
            actual_s, actual_a = read_actual_strategy(slug)
            base_row["actual_strategy"] = actual_s
            base_row["actual_adapter"] = actual_a
            insert_run(conn, base_row)
            return base_row
        if _is_already_rejected(slug):
            base_row["status"] = "already_rejected"
            base_row["reason"] = "REJECTED 마커 존재"
            insert_run(conn, base_row)
            return base_row
        if _is_bug_marked(slug):
            base_row["status"] = "bug_marked"
            base_row["reason"] = "BUG.json 마커 — 코드 결함, register.py --clear-bug 로 풀어야 재시도"
            insert_run(conn, base_row)
            return base_row
        age = _failed_age_days(slug)
        if age is not None and age < args.cooldown_days:
            base_row["status"] = "recent_fail_skip"
            base_row["reason"] = f".FAILED.json age={age:.1f}d < cooldown {args.cooldown_days}d"
            insert_run(conn, base_row)
            return base_row
        if slug in _load_triage_later():
            base_row["status"] = "triage_later"
            base_row["reason"] = "triage_later.json"
            insert_run(conn, base_row)
            return base_row

    if args.dry_run:
        base_row["status"] = "untried"
        base_row["reason"] = "dry-run"
        insert_run(conn, base_row)
        return base_row

    # 실행
    cmd = [sys.executable, str(REGISTER_PY), url, "--max-attempts", str(args.max_attempts)]
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            errors="replace", timeout=args.timeout,
            cwd=str(ROOT),
        )
        rc = proc.returncode
        stderr = proc.stderr or ""
    except subprocess.TimeoutExpired:
        rc = -1
        stderr = "TimeoutExpired"
    duration = time.time() - t0

    base_row["duration_s"] = round(duration, 2)
    base_row["rc"] = rc
    base_row["stderr_tail"] = (stderr or "")[-2000:]

    if rc == -1:
        base_row["status"] = "timeout"
        base_row["reason"] = f"register.py timeout ({args.timeout}s)"
    else:
        status, reason = classify_outcome(slug, rc, stderr)
        base_row["status"] = status
        base_row["reason"] = reason
        if status == "registered":
            actual_s, actual_a = read_actual_strategy(slug)
            base_row["actual_strategy"] = actual_s
            base_row["actual_adapter"] = actual_a

    insert_run(conn, base_row)
    return base_row


# --------------------------------------------------------------------------- #
# Filter + iterate
# --------------------------------------------------------------------------- #
def _last_attempt_ts_per_cand(conn: sqlite3.Connection) -> dict[str, str]:
    """cand_id → 최신 ts (ISO). 한 번도 시도 안 됐으면 dict 에서 빠짐."""
    out: dict[str, str] = {}
    try:
        rows = conn.execute(
            "SELECT cand_id, MAX(ts) FROM runs GROUP BY cand_id"
        ).fetchall()
    except sqlite3.Error:
        return out
    for cid, ts in rows:
        if cid and ts:
            out[cid] = ts
    return out


def _sort_least_attempted_first(entries: list[dict]) -> list[dict]:
    """미시도 (last_ts NULL) 가 먼저, 그 다음 last_ts 오래된 순. 동률은 entry id 알파벳.

    plan §5: `--limit` 와 함께 의미 있는 chunk-by-chunk 진행을 위해.
    runs DB 가 비어있으면 entries 원본 순서 유지.
    """
    conn = open_runs_db()
    try:
        last_ts = _last_attempt_ts_per_cand(conn)
    finally:
        conn.close()
    if not last_ts:
        return list(entries)
    # 미시도 = ts "" (정렬상 가장 작음). entries 안 변형.
    return sorted(entries, key=lambda e: (last_ts.get(e["id"], ""), e["id"]))


def filter_entries(entries: list[dict], args) -> list[dict]:
    def _split(s):
        return {x.strip() for x in (s or "").split(",") if x.strip()}
    cats = _split(args.category)
    tiers = _split(args.tier)
    provs = _split(args.provenance)
    out = []
    for e in entries:
        if cats and e["category"] not in cats:
            continue
        if tiers and e["tier"] not in tiers:
            continue
        if provs and (e.get("source") or {}).get("provenance") not in provs:
            continue
        out.append(e)
    return out


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="사이트 카탈로그 일괄 등록 driver")
    p.add_argument("--catalog", default=str(CATALOG_DEFAULT),
                   help=f"catalog.yaml 경로 (기본 {CATALOG_DEFAULT.relative_to(ROOT)})")
    p.add_argument("--category", default="",
                   help=f"카테고리 필터 (콤마구분). 가능: {sorted(ALLOWED_CATEGORIES)}")
    p.add_argument("--tier", default="", help="tier 필터 A~G (콤마구분)")
    p.add_argument("--provenance", default="", help="provenance 필터 doc|history|web (콤마구분)")
    p.add_argument("--limit", type=int, default=0, help="처리할 entry 상한 (0=무한)")
    p.add_argument("--max-attempts", type=int, default=4, help="register.py 의 --max-attempts")
    p.add_argument("--cooldown-days", type=float, default=7.0,
                   help="같은 slug 의 .FAILED.json 이 이 일수 이내면 skip (기본 7)")
    p.add_argument("--timeout", type=int, default=900,
                   help="register.py 1회 호출 timeout 초 (기본 900=15분)")
    p.add_argument("--dry-run", action="store_true",
                   help="실제 register 안 돌리고 skip 판단만 (current state 분포 보기)")
    p.add_argument("--force", action="store_true",
                   help="이미 registered/rejected/failed 라도 다시 시도")
    p.add_argument("--pull-snapshot", action="store_true",
                   help="실행 전 `scripts/triage.py pull` 로 N100 snapshot 갱신 (configs.snapshot + output/snapshot/poll_state). "
                        "기본 OFF — codex review 권고로 opt-in. 스냅샷 stale 우려 시만 켜기.")
    args = p.parse_args(argv)

    if args.pull_snapshot:
        triage_cmd = [sys.executable, str(ROOT / "scripts" / "triage.py"), "pull", "--skip-later"]
        print(f"[batch] pull snapshot: {' '.join(triage_cmd[1:])}")
        try:
            rc_pull = subprocess.call(triage_cmd, cwd=str(ROOT))
        except OSError as e:
            print(f"[batch] snapshot pull 실패: {e} — stale snapshot 으로 진행", file=sys.stderr)
        else:
            if rc_pull != 0:
                print(f"[batch] snapshot pull rc={rc_pull} — stale snapshot 으로 진행", file=sys.stderr)

    catalog_path = Path(args.catalog)
    try:
        entries = load_catalog(catalog_path)
    except FileNotFoundError as e:
        print(f"[batch] {e}", file=sys.stderr)
        return 3
    except (ValueError, OSError, TypeError, KeyError) as e:
        print(f"[batch] catalog 검증 실패: {e}", file=sys.stderr)
        return 2

    selected = filter_entries(entries, args)
    if args.limit > 0:
        # least-attempted first ordering (plan §5 + codex review #3).
        selected = _sort_least_attempted_first(selected)
        selected = selected[: args.limit]

    print(f"[batch] catalog={catalog_path.relative_to(ROOT)} entries={len(entries)} selected={len(selected)} "
          f"dry_run={args.dry_run} force={args.force} cooldown_days={args.cooldown_days}")

    conn = open_runs_db()
    try:
        from collections import Counter
        status_counter: Counter[str] = Counter()
        total_boards = sum(len(e.get("boards") or []) for e in selected)
        idx = 0
        for e in selected:
            for b in (e.get("boards") or []):
                idx += 1
                row = run_one(e, b, args, conn)
                status_counter[row["status"]] += 1
                strat = row.get("actual_strategy") or "—"
                print(f"  [{idx}/{total_boards}] {row['status']:<22} "
                      f"{e['id']:<32} {strat:<14} {b['url'][:80]}")
                if row.get("reason"):
                    print(f"       └ {row['reason'][:200]}")
    finally:
        conn.close()

    print("\n[batch] 요약:")
    for st, n in sorted(status_counter.items(), key=lambda kv: -kv[1]):
        print(f"  {st:<22} {n}")
    print(f"  TOTAL                  {sum(status_counter.values())}")
    print(f"[batch] runs DB: {RUNS_DB.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
