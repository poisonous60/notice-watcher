"""migrate_slug_schema.py — slug 형식을 `host_path_query` (옛) → `<platform>_<board-id>_<hash>` (새) 로 일괄 마이그.

배경
  새 slug 형식은 `engine.slug.url_to_slug` 가 생성. recognizer 가 매칭하면 `<platform>_<board-id>_<hash>`,
  미등록 사이트는 `host_<host-dashed>_<seg>_<hash>`. Discord autocomplete 의 100자 hard limit + `/list`
  의 가독성 둘 다 해결하기 위해 도입. 단 *기존 slug 가 박힌 곳이 많아서* (DB 5 테이블, configs/, poll_state/,
  output/probe/) 일괄 rename 필요.

흐름 (idempotent — old==new 면 skip):
  1. Mapping 빌드:
     poll_state/*.json (`url` 필드) → new_slug
     orphan 인 subscriptions/jobs/deliveries/pending/reports.slug 도 보강
     configs/*.json 의 `_source_url` 도 보강
  2. Dry-run 표 출력 (--dry-run 이면 종료)
  3. DB 트랜잭션: 5 테이블 UPDATE
  4. FS rename: configs/, poll_state/, probe/ + 안의 slug/config_path 필드 재기록
  5. `output/collected/` 통째로 삭제 (--collected-mode clear; 옵션 keep 으로 보존 가능)
  6. `output/triage_queue.jsonl` 의 slug 필드 갱신
  7. Sanity check: DB row count pre/post 동일

사용:
  python scripts/migrate_slug_schema.py --dry-run                  # 매핑만 출력
  python scripts/migrate_slug_schema.py --yes                      # 실행 (확인 없이)
  python scripts/migrate_slug_schema.py --yes --collected-mode keep

N100 배포 절차 (운영 메모 §8 부록): services stop → git pull → dry-run → real run → start.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.slug import url_to_slug  # noqa: E402

DEFAULT_DB = ROOT / "output" / "bot.sqlite3"
DEFAULT_CONFIGS = ROOT / "configs"
DEFAULT_STATE = ROOT / "output" / "poll_state"
DEFAULT_PROBE = ROOT / "output" / "probe"
DEFAULT_COLLECTED = ROOT / "output" / "collected"
DEFAULT_TRIAGE = ROOT / "output" / "triage_queue.jsonl"
LOCK_FILE = ROOT / "output" / ".migrate-slug.lock"

_DB_TABLES = ["subscriptions", "jobs", "deliveries", "pending", "reports"]

# poll_state/ 안의 marker suffix — `.json` (등록 성공 state) + 네 가지 marker.
# build_mapping 이 stem 추출 시 모두 strip 해야 mapping key 가 *slug 그 자체* 가 됨.
# rename_state 가 rename 시에도 모든 suffix 형태 처리해야 marker 손실 방지.
# BROKEN 은 health sidecar — slug rename 시 같이 따라가야 stale 안 남음.
_MARKER_SUFFIXES = (".FAILED", ".REJECTED", ".BUG", ".BROKEN")
_STATE_FILE_SUFFIXES = (".json", ".FAILED.json", ".REJECTED.json", ".BUG.json", ".BROKEN.json")


# --------------------------------------------------------------------------- #
# 1) 매핑 빌드
# --------------------------------------------------------------------------- #
def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def build_mapping(state_dir: Path, configs_dir: Path,
                  conn: sqlite3.Connection | None) -> dict[str, dict]:
    """{old_slug: {"new_slug": str, "url": str, "source": str}} 반환.

    source 우선순위: poll_state > subscriptions.url > jobs.url > configs._source_url.
    """
    mapping: dict[str, dict] = {}

    # (1) poll_state/*.json — `.json` 등록 성공 state + `.FAILED.json` / `.REJECTED.json` / `.BUG.json` 마커.
    #     marker suffix 는 *모두* strip 해 stem=slug 로 만들어야 mapping key 가 일관. 안 그러면 stem 에 `.REJECTED`
    #     남아 rename_state 가 marker 파일을 normal state file 로 변환하는 critical 버그 발생 (codex 발견).
    if state_dir.exists():
        for p in state_dir.glob("*.json"):
            stem = p.name[:-len(".json")]
            for marker in _MARKER_SUFFIXES:
                if stem.endswith(marker):
                    stem = stem[:-len(marker)]
                    break
            d = _read_json(p)
            if d and d.get("url"):
                url = d["url"]
                mapping.setdefault(stem, {
                    "new_slug": url_to_slug(url), "url": url, "source": "poll_state",
                })

    # (2) DB rows — subscriptions / jobs (url 컬럼)
    if conn is not None:
        for row in conn.execute("SELECT slug, url FROM subscriptions WHERE url IS NOT NULL"):
            old, url = row[0], row[1]
            if old not in mapping and url:
                mapping[old] = {"new_slug": url_to_slug(url), "url": url, "source": "subscriptions"}
        for row in conn.execute("SELECT slug, url FROM jobs WHERE url IS NOT NULL ORDER BY id DESC"):
            old, url = row[0], row[1]
            if old not in mapping and url:
                mapping[old] = {"new_slug": url_to_slug(url), "url": url, "source": "jobs"}

    # (3) configs/*.json (`_source_url`)
    if configs_dir.exists():
        for p in configs_dir.glob("*.json"):
            stem = p.stem
            if stem in mapping:
                continue
            d = _read_json(p)
            if d and d.get("_source_url"):
                url = d["_source_url"]
                mapping[stem] = {"new_slug": url_to_slug(url), "url": url, "source": "configs"}

    return mapping


def detect_collisions(mapping: dict[str, dict]) -> list[tuple[str, list[str]]]:
    """동일 new_slug 로 매핑되는 old_slug 들 (서로 다른 URL) — 충돌."""
    by_new: dict[str, list[str]] = {}
    for old, info in mapping.items():
        by_new.setdefault(info["new_slug"], []).append(old)
    return [(new, olds) for new, olds in by_new.items() if len(olds) > 1]


# --------------------------------------------------------------------------- #
# 2) 출력
# --------------------------------------------------------------------------- #
def print_mapping(mapping: dict[str, dict]) -> None:
    rename_count = sum(1 for old, info in mapping.items() if old != info["new_slug"])
    noop_count = len(mapping) - rename_count
    print(f"매핑: 총 {len(mapping)}건 (rename {rename_count} / no-op {noop_count})")
    print()
    print(f"{'OLD':<70}  →  {'NEW':<55}  [source]")
    print("-" * 140)
    for old, info in sorted(mapping.items()):
        marker = "  " if old == info["new_slug"] else "* "
        print(f"{marker}{old:<68}  →  {info['new_slug']:<55}  [{info['source']}]")
    print()


# --------------------------------------------------------------------------- #
# 3) DB UPDATE (transactional)
# --------------------------------------------------------------------------- #
def apply_db(conn: sqlite3.Connection, mapping: dict[str, dict]) -> dict[str, int]:
    """5 테이블의 slug 컬럼 UPDATE. 트랜잭션 1개. 반환: {table: rows_changed}."""
    counts_before: dict[str, int] = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in _DB_TABLES
    }
    changes: dict[str, int] = {t: 0 for t in _DB_TABLES}

    try:
        conn.execute("BEGIN IMMEDIATE")
        for old, info in mapping.items():
            new = info["new_slug"]
            if old == new:
                continue
            for t in _DB_TABLES:
                cur = conn.execute(f"UPDATE {t} SET slug=? WHERE slug=?", (new, old))
                changes[t] += cur.rowcount
        conn.commit()
    except sqlite3.IntegrityError as e:
        conn.rollback()
        sys.stderr.write(f"[migrate] DB UPDATE 실패 (rollback): {e}\n")
        raise

    counts_after: dict[str, int] = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in _DB_TABLES
    }
    for t in _DB_TABLES:
        if counts_before[t] != counts_after[t]:
            sys.stderr.write(
                f"[migrate] ⚠ {t} row count drift: before={counts_before[t]} after={counts_after[t]}\n"
            )
    return changes


# --------------------------------------------------------------------------- #
# 4) FS rename + 내부 필드 재기록
# --------------------------------------------------------------------------- #
def rename_config(configs_dir: Path, old: str, new: str) -> bool:
    """configs/<old>.json → configs/<new>.json."""
    src = configs_dir / f"{old}.json"
    dst = configs_dir / f"{new}.json"
    if not src.exists():
        return False
    try:
        os.replace(src, dst)
        return True
    except OSError as e:
        sys.stderr.write(f"[migrate] configs rename 실패: {src} → {dst} ({e})\n")
        return False


def rename_state(state_dir: Path, configs_dir: Path, old: str, new: str) -> bool:
    """poll_state/<old>{.json|.FAILED.json|.REJECTED.json|.BUG.json} → <new>{같은 suffix} +
    내부 `slug` 와 `config_path` 필드 재기록. marker 4종 모두 같은 suffix 보존 — 안 그러면 marker 손실.
    """
    moved_any = False
    for suffix in _STATE_FILE_SUFFIXES:
        src = state_dir / f"{old}{suffix}"
        dst = state_dir / f"{new}{suffix}"
        if not src.exists():
            continue
        d = _read_json(src)
        if d is None:
            try:
                os.replace(src, dst)
                moved_any = True
            except OSError as e:
                sys.stderr.write(f"[migrate] state rename 실패: {src} → {dst} ({e})\n")
            continue
        d["slug"] = new
        # config_path 안의 stem 만 갱신 (Windows / POSIX 둘 다 안전).
        cp = d.get("config_path")
        if cp:
            try:
                cp_new = Path(cp).with_name(f"{new}.json")
                d["config_path"] = str(cp_new)
            except (ValueError, OSError):
                pass
        try:
            dst.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
            src.unlink()
            moved_any = True
        except OSError as e:
            sys.stderr.write(f"[migrate] state 재기록 실패: {src} → {dst} ({e})\n")
    return moved_any


def rename_probe(probe_dir: Path, old: str, new: str) -> bool:
    """output/probe/<old>/ → <new>/."""
    src = probe_dir / old
    dst = probe_dir / new
    if not src.exists() or not src.is_dir():
        return False
    if dst.exists():
        sys.stderr.write(f"[migrate] probe dest 이미 존재 — skip: {dst}\n")
        return False
    try:
        os.replace(src, dst)
        return True
    except OSError as e:
        sys.stderr.write(f"[migrate] probe rename 실패: {src} → {dst} ({e})\n")
        return False


def apply_fs(state_dir: Path, configs_dir: Path, probe_dir: Path,
              mapping: dict[str, dict]) -> dict[str, int]:
    counts = {"configs": 0, "state": 0, "probe": 0}
    for old, info in mapping.items():
        new = info["new_slug"]
        if old == new:
            continue
        if rename_config(configs_dir, old, new):
            counts["configs"] += 1
        if rename_state(state_dir, configs_dir, old, new):
            counts["state"] += 1
        if rename_probe(probe_dir, old, new):
            counts["probe"] += 1
    return counts


def apply_collected(collected_dir: Path, mode: str) -> str:
    if mode == "keep":
        return "kept as-is"
    if mode == "clear":
        if collected_dir.exists():
            shutil.rmtree(collected_dir, ignore_errors=True)
        return "cleared"
    raise ValueError(f"invalid collected-mode: {mode}")


def rewrite_triage_queue(triage_jsonl: Path, mapping: dict[str, dict]) -> int:
    """triage_queue.jsonl 의 각 라인 `slug` 필드 mapping 적용. 갱신된 라인 수 반환."""
    if not triage_jsonl.exists():
        return 0
    changed = 0
    lines_out: list[str] = []
    for line in triage_jsonl.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            lines_out.append(line)
            continue
        old = d.get("slug")
        if old in mapping and old != mapping[old]["new_slug"]:
            d["slug"] = mapping[old]["new_slug"]
            changed += 1
        lines_out.append(json.dumps(d, ensure_ascii=False))
    if lines_out:
        triage_jsonl.write_text("\n".join(lines_out) + "\n", encoding="utf-8")
    return changed


# --------------------------------------------------------------------------- #
# 5) lock
# --------------------------------------------------------------------------- #
class _Lock:
    def __init__(self, path: Path):
        self.path = path
        self.acquired = False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            # exclusive create — 다른 프로세스가 이미 실행 중이면 OSError
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            self.acquired = True
        except FileExistsError:
            sys.stderr.write(f"[migrate] lock 존재 — 다른 마이그가 실행 중? ({self.path})\n")
            sys.stderr.write("[migrate] 다른 프로세스 없으면 lock 파일 직접 삭제 후 재실행.\n")
            sys.exit(2)
        return self

    def __exit__(self, *exc):
        if self.acquired:
            try:
                self.path.unlink()
            except OSError:
                pass


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true", help="매핑만 출력하고 종료")
    p.add_argument("--yes", action="store_true", help="확인 없이 진행")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--configs", type=Path, default=DEFAULT_CONFIGS)
    p.add_argument("--state", type=Path, default=DEFAULT_STATE)
    p.add_argument("--probe", type=Path, default=DEFAULT_PROBE)
    p.add_argument("--collected", type=Path, default=DEFAULT_COLLECTED)
    p.add_argument("--triage", type=Path, default=DEFAULT_TRIAGE)
    p.add_argument("--collected-mode", choices=["clear", "keep"], default="clear",
                   help="collected/ 처리 (기본: clear)")
    args = p.parse_args(argv)

    # DB 열기 (없어도 dev clone 처럼 진행 가능)
    conn: sqlite3.Connection | None = None
    if args.db.exists():
        conn = sqlite3.connect(str(args.db), timeout=15.0)
        conn.row_factory = sqlite3.Row
    else:
        print(f"[migrate] DB 없음 ({args.db}) — DB 단계 skip (configs/state 만 진행)")

    print(f"[migrate] DB={args.db}  configs={args.configs}  state={args.state}  probe={args.probe}")
    print()

    # mapping
    mapping = build_mapping(args.state, args.configs, conn)
    if not mapping:
        print("[migrate] 매핑 항목 0건 — 마이그할 게 없습니다.")
        return 0

    cols = detect_collisions(mapping)
    if cols:
        sys.stderr.write("[migrate] ⚠ 새 slug 충돌 감지 — 마이그 중단:\n")
        for new, olds in cols:
            sys.stderr.write(f"  {new} ← {', '.join(olds)}\n")
        return 3

    print_mapping(mapping)

    if args.dry_run:
        print("[migrate] --dry-run — 변경 없음.")
        if conn:
            conn.close()
        return 0

    if not args.yes:
        print("[migrate] --yes 없음 — 안전을 위해 dry-run 으로 종료. 실행하려면 --yes 추가.")
        if conn:
            conn.close()
        return 0

    # 잠금 + 실행
    with _Lock(LOCK_FILE):
        if conn is not None:
            print("[migrate] DB UPDATE 적용 중...")
            db_changes = apply_db(conn, mapping)
            print(f"[migrate] DB 변경: {db_changes}")

        print("[migrate] FS rename 적용 중...")
        fs_changes = apply_fs(args.state, args.configs, args.probe, mapping)
        print(f"[migrate] FS rename: {fs_changes}")

        coll_status = apply_collected(args.collected, args.collected_mode)
        print(f"[migrate] collected/: {coll_status}")

        triage_changes = rewrite_triage_queue(args.triage, mapping)
        print(f"[migrate] triage_queue.jsonl: {triage_changes}건 갱신")

    if conn is not None:
        conn.close()
    print("[migrate] ✅ 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
