"""BROKEN sidecar 도입 후 1회 migration — zombie reset + stale FAILED 정리 + real broken 마커 박음.

배포 순서 (HARD-STOP):
1. 이 스크립트가 의존하는 code (state-scanner BROKEN exclusion + `_save_broken` 등) 가
   N100 에 이미 배포되어 있어야 함 — 안 그러면 poll.py 가 `.BROKEN.json` 을 정상 state 로
   파싱 시도 → crash.
2. 본 스크립트는 N100 의 output/poll_state/ 만 건드림 (CLAUDE.md §3 룰 B 예외 — git 추적 X).
3. dev box 에서 실행은 의미 없음 (state file 은 N100 실시간).

분기:
  - **zombie (stale FAILED + cb>0 + subscription 있음)** → `.FAILED.json` unlink + cb=0 reset.
    (다음 poll 가 또 깨지면 cb 재누적 후 broken_threshold 도달 시 자연 BROKEN 박힘 — 잘 작동.)
  - **real broken (cb >= broken_threshold + 차단 마커 없음)** → `.BROKEN.json` 박음.
  - **transient (cb < broken_threshold)** → 그대로 (다음 poll 에서 자연 해소 가능).

기본 dry-run. 실행 = `--yes`. rollback = `--clear-all --yes`.
실행 직전 `output/poll_state.backup_<ts>.tar.gz` 자동 생성 (안전망).

사용:
  python scripts/migrate_broken_zombie.py --dry-run    # 기본
  python scripts/migrate_broken_zombie.py --yes        # 실행
  python scripts/migrate_broken_zombie.py --clear-all --dry-run
  python scripts/migrate_broken_zombie.py --clear-all --yes  # rollback (BROKEN sidecar 전부 unlink)
"""
from __future__ import annotations

import argparse
import json
import sys
import sqlite3
import tarfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.runtime_config import settings  # noqa: E402

STATE_DIR = ROOT / "output" / "poll_state"
BOT_DB = ROOT / "output" / "bot.sqlite3"
MARKER_SUFFIXES = (".FAILED.json", ".REJECTED.json", ".BUG.json", ".BROKEN.json")


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _subscribed_slugs(db_path: Path) -> set[str]:
    if not db_path.exists():
        return set()
    try:
        conn = sqlite3.connect(str(db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT DISTINCT slug FROM subscriptions").fetchall()
        conn.close()
        return {r[0] for r in rows}
    except sqlite3.Error as e:
        print(f"[migrate] subscriptions 조회 실패 (계속 진행): {e}", file=sys.stderr)
        return set()


def _scan_state(only: set[str] | None = None) -> list[dict]:
    """state.json 파일들 — marker 제외, cb / 마커 동반 정보."""
    out: list[dict] = []
    if not STATE_DIR.exists():
        return out
    for p in STATE_DIR.glob("*.json"):
        n = p.name
        if any(n.endswith(suf) for suf in MARKER_SUFFIXES):
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        slug = d.get("slug") or n[:-len(".json")]
        if only and slug not in only:
            continue
        cb = int(d.get("consecutive_breakage", 0) or 0)
        out.append({
            "slug": slug,
            "url": d.get("url", "") or "",
            "cb": cb,
            "last_status": d.get("last_status", "") or "",
            "has_failed": (STATE_DIR / f"{slug}.FAILED.json").exists(),
            "has_rejected": (STATE_DIR / f"{slug}.REJECTED.json").exists(),
            "has_bug": (STATE_DIR / f"{slug}.BUG.json").exists(),
            "has_broken": (STATE_DIR / f"{slug}.BROKEN.json").exists(),
        })
    return out


def _classify(rows: list[dict], subscribed: set[str], broken_threshold: int) -> dict[str, list[dict]]:
    """rows 는 *_scan_state* 가 이미 state.json 있는 slug 만 반환 — `.FAILED.json` 동시 존재 = stale.

    subscribed 는 분류 카운트 보조 정보 (zombie 가 활성 구독자에 영향 있는지 판단)지 분기 조건 아님.
    state.json + FAILED.json 동시 = 자동으로 stale (poll.py 가 state.json 으로 폴링 진행하지만
    is_blocked=True 라 reprobe rc=-7 영구 fast-skip). 구독자 없어도 lurking 슬러그 정리는 가치 있음.
    """
    out = {"zombie": [], "real_broken": [], "transient": [], "noop": []}
    for r in rows:
        r["subscribed"] = r["slug"] in subscribed  # 표시용
        if r["cb"] <= 0:
            out["noop"].append(r)
            continue
        # 우선순위 마커 (FAILED stale 제외) — 차단 마커 있으면 손대지 않음.
        if r["has_rejected"] or r["has_bug"]:
            out["noop"].append(r)
            continue
        if r["has_failed"]:
            # FAILED stale: state.json 살아있음 + FAILED 잔재 → FAILED unlink + cb reset
            out["zombie"].append(r)
        elif r["cb"] >= broken_threshold and not r["has_broken"]:
            # 진짜 broken: 마커 없고 임계 도달 → BROKEN 박음
            out["real_broken"].append(r)
        else:
            out["transient"].append(r)
    return out


def _threshold_table(rows: list[dict]) -> str:
    cb_counter: Counter[int] = Counter(r["cb"] for r in rows if r["cb"] > 0)
    lines = ["cb 분포 (cb>0):"]
    for cb in sorted(cb_counter.keys(), reverse=True):
        lines.append(f"  cb={cb}: {cb_counter[cb]}건")
    lines.append("")
    lines.append("threshold 별 BROKEN 후보 카운트 (FAILED·REJECTED·BUG 우선 마커 제외):")
    for t in (3, 4, 6, 8):
        n = sum(1 for r in rows
                if r["cb"] >= t and not r["has_rejected"] and not r["has_bug"]
                and not r["has_failed"])
        lines.append(f"  threshold={t}: {n}건")
    return "\n".join(lines)


def _tar_backup() -> Path:
    """`output/poll_state/` 전체 tar.gz backup. rollback 안전망."""
    if not STATE_DIR.exists():
        raise SystemExit(f"[migrate] STATE_DIR 없음: {STATE_DIR}")
    backup = ROOT / "output" / f"poll_state.backup_{_now_ts()}.tar.gz"
    with tarfile.open(backup, "w:gz") as tf:
        tf.add(STATE_DIR, arcname="poll_state")
    return backup


def _do_migrate(buckets: dict[str, list[dict]], *, dry_run: bool, broken_threshold: int) -> None:
    print(f"\n--- migrate plan (broken_threshold={broken_threshold}) ---")
    print(f"  zombie (stale FAILED + state.json 살아있음 + cb>0): {len(buckets['zombie'])}")
    print(f"  real_broken (cb>=threshold, 마커 없음):              {len(buckets['real_broken'])}")
    print(f"  transient (cb<threshold + 마커 없음):                {len(buckets['transient'])}")
    print(f"  noop (cb=0 또는 REJECTED/BUG 있음):                  {len(buckets['noop'])}")
    print()
    for kind in ("zombie", "real_broken"):
        if not buckets[kind]:
            continue
        print(f"  [{kind}] 후보:")
        for r in sorted(buckets[kind], key=lambda x: -x["cb"])[:30]:
            sub = "★sub" if r.get("subscribed") else "lurking"
            print(f"    cb={r['cb']:>3}  {sub:<7}  slug={r['slug']}  last_status={r['last_status']}")
        if len(buckets[kind]) > 30:
            print(f"    ... +{len(buckets[kind]) - 30}건")
    if dry_run:
        print("\n(dry-run — 변경 없음. 실행하려면 --yes)")
        return

    # 실행 — backup 먼저
    backup = _tar_backup()
    print(f"\n[migrate] tar backup 박음: {backup}")

    # zombie: FAILED unlink + cb reset
    from scripts.register import _clear_broken  # noqa: PLC0415  (마커 정리 idempotent helper)
    n_failed_cleared = 0
    n_cb_reset = 0
    for r in buckets["zombie"]:
        slug = r["slug"]
        fp = STATE_DIR / f"{slug}.FAILED.json"
        sp = STATE_DIR / f"{slug}.json"
        if fp.exists():
            try:
                fp.unlink()
                n_failed_cleared += 1
            except OSError as e:
                print(f"  ⚠ {fp.name} unlink 실패: {e}", file=sys.stderr)
        if sp.exists():
            try:
                d = json.loads(sp.read_text(encoding="utf-8"))
                if int(d.get("consecutive_breakage", 0) or 0) > 0:
                    d["consecutive_breakage"] = 0
                    d["last_status"] = "migrated_zombie_reset"
                    sp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
                    n_cb_reset += 1
            except Exception as e:  # noqa: BLE001
                print(f"  ⚠ {sp.name} cb reset 실패: {e}", file=sys.stderr)
        # BROKEN sidecar 잔재 있으면 cb reset 동안 함께 정리 (idempotent).
        _clear_broken(slug)
    print(f"[migrate] zombie 처리: FAILED unlink {n_failed_cleared}건, cb reset {n_cb_reset}건")

    # real broken: BROKEN sidecar 박음
    from scripts.register import _save_broken  # noqa: PLC0415
    n_broken_saved = 0
    for r in buckets["real_broken"]:
        try:
            _save_broken(r["slug"], r["url"],
                          cb=r["cb"], last_status=r["last_status"],
                          last_note="migrate_broken_zombie initial mark")
            n_broken_saved += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ _save_broken({r['slug']}) 실패: {e}", file=sys.stderr)
    print(f"[migrate] real_broken 처리: BROKEN sidecar {n_broken_saved}건 박음")


def _do_clear_all(*, dry_run: bool) -> None:
    """rollback — `.BROKEN.json` 전부 unlink. cb state 는 그대로."""
    if not STATE_DIR.exists():
        print("[migrate] STATE_DIR 없음 — 할 일 없음")
        return
    targets = sorted(STATE_DIR.glob("*.BROKEN.json"))
    print(f"[migrate --clear-all] BROKEN sidecar {len(targets)}개 unlink 후보:")
    for p in targets[:30]:
        print(f"  {p.name}")
    if len(targets) > 30:
        print(f"  ... +{len(targets) - 30}건")
    if dry_run:
        print("(dry-run — 변경 없음. 실행하려면 --yes)")
        return
    backup = _tar_backup()
    print(f"\n[migrate --clear-all] tar backup 박음: {backup}")
    n = 0
    for p in targets:
        try:
            p.unlink()
            n += 1
        except OSError as e:
            print(f"  ⚠ {p.name} unlink 실패: {e}", file=sys.stderr)
    print(f"[migrate --clear-all] {n}개 unlink 완료")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", default=True,
                    help="기본 — 실제 변경 안 함 (분류 표만 출력)")
    ap.add_argument("--yes", dest="dry_run", action="store_false",
                    help="실제 실행 — tar backup 후 zombie reset + BROKEN sidecar 박음")
    ap.add_argument("--clear-all", action="store_true",
                    help="rollback — `.BROKEN.json` 전부 unlink (cb state 는 그대로)")
    ap.add_argument("--threshold", type=int, default=None,
                    help=f"broken_threshold override (기본 {settings.poll.broken_threshold})")
    args = ap.parse_args(argv)

    threshold = args.threshold if args.threshold is not None else settings.poll.broken_threshold
    if args.clear_all:
        _do_clear_all(dry_run=args.dry_run)
        return 0

    rows = _scan_state()
    subscribed = _subscribed_slugs(BOT_DB)
    print(_threshold_table(rows))
    print()
    print(f"전체 state 파일 (cb>0): {sum(1 for r in rows if r['cb'] > 0)}건")
    print(f"구독 활성 slug: {len(subscribed)}건")

    buckets = _classify(rows, subscribed, broken_threshold=threshold)
    _do_migrate(buckets, dry_run=args.dry_run, broken_threshold=threshold)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
