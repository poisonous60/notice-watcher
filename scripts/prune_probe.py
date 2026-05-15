"""`output/probe/<slug>/` 디스크 정리 — N100 cron 으로 호출.

probe 산출물(HAR/screenshot/JS bundle)은 1 slug 당 수 MB ~ 수십 MB. 비공개·로그인필요 사이트 같은
영구 실패 케이스가 누적되면 GB 단위로 부풀음. 이 스크립트는 두 카테고리로 나눠 mtime 기준으로 prune.

기준 (settings.prune):
  - probe_failed_max_age_days   : 같은 slug 의 `output/poll_state/<slug>.FAILED.json` 있고 그 마커가
                                  N일 이상 됐으면 → probe artifact prune. 자동 등록은 그 마커가 풀릴 때까지
                                  안 됨 → artifact 보존 가치 낮음.
  - probe_unregistered_max_age_days : `poll_state/<slug>.json` 도 `.FAILED.json` 도 `.REJECTED.json` 도
                                  없는 orphan probe (한 번 등록 시도 했지만 흔적 사라짐, 또는 register 진행
                                  중 죽음). N일 이상 됐으면 prune.

각 값 ≤0 이면 그 카테고리 prune 끔. 등록된 slug (`.json` 있고 FAILED 없음) 은 절대 안 건드림 —
폴링 진단·재-probe 용으로 살아있어야 함.

사용:
    python scripts/prune_probe.py            # dry-run (기본 — 후보만 출력, 실제 삭제 X)
    python scripts/prune_probe.py --yes      # 실제 삭제
    python scripts/prune_probe.py --verbose  # 보존 사유까지 표시
    python scripts/prune_probe.py --dry-run  # --yes 없으면 동작 같음 — 명시적

cron (N100):
    0 4 * * * cd ~/notice-watcher && .venv/bin/python scripts/prune_probe.py --yes >> output/prune.log 2>&1

`shutil.rmtree` destructive — 기본 dry-run 으로 사람이 한 번 검토하게(`migrate_slug_schema.py --yes` 와 같은 패턴).
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.runtime_config import settings  # noqa: E402


PROBE_DIR = ROOT / "output" / "probe"
STATE_DIR = ROOT / "output" / "poll_state"


def _mtime_age_days(p: Path) -> float:
    return (time.time() - p.stat().st_mtime) / 86400.0


def _classify(slug_dir: Path) -> tuple[str, float]:
    """카테고리 분류 + age. 반환: (category, age_days).
      - "registered"    : 정상 등록 중 — 절대 안 건드림
      - "rejected"      : owner 가 거부 마커 박은 slug — 보존 (참고용)
      - "failed"        : .FAILED.json 마커 — probe_failed_max_age_days 적용
      - "unregistered"  : 셋 다 없음 — probe_unregistered_max_age_days 적용
    """
    slug = slug_dir.name
    age = _mtime_age_days(slug_dir)
    has_state = (STATE_DIR / f"{slug}.json").exists()
    has_failed = (STATE_DIR / f"{slug}.FAILED.json").exists()
    has_rejected = (STATE_DIR / f"{slug}.REJECTED.json").exists()
    if has_state and not has_failed:
        return ("registered", age)
    if has_rejected:
        return ("rejected", age)
    if has_failed:
        return ("failed", age)
    return ("unregistered", age)


def prune(*, dry_run: bool = False, verbose: bool = False) -> int:
    """반환: 삭제(또는 dry-run 매치)된 디렉토리 수."""
    if not PROBE_DIR.exists():
        print(f"[prune_probe] {PROBE_DIR} 없음 — skip")
        return 0
    failed_days = settings.prune.probe_failed_max_age_days
    unreg_days = settings.prune.probe_unregistered_max_age_days
    print(f"[prune_probe] threshold — failed: {failed_days}d / unregistered: {unreg_days}d"
          f"  (dry_run={dry_run})")
    n_removed = 0
    n_kept = {"registered": 0, "rejected": 0, "failed_young": 0, "unregistered_young": 0,
              "failed_disabled": 0, "unregistered_disabled": 0}
    for slug_dir in sorted(PROBE_DIR.iterdir()):
        if not slug_dir.is_dir():
            continue
        cat, age = _classify(slug_dir)
        if cat == "registered":
            n_kept["registered"] += 1
            if verbose:
                print(f"  KEEP {slug_dir.name}  (registered, age={age:.1f}d)")
            continue
        if cat == "rejected":
            n_kept["rejected"] += 1
            if verbose:
                print(f"  KEEP {slug_dir.name}  (rejected, age={age:.1f}d)")
            continue
        if cat == "failed":
            if failed_days <= 0:
                n_kept["failed_disabled"] += 1
                if verbose:
                    print(f"  KEEP {slug_dir.name}  (failed, threshold disabled)")
                continue
            if age < failed_days:
                n_kept["failed_young"] += 1
                if verbose:
                    print(f"  KEEP {slug_dir.name}  (failed, age={age:.1f}d < {failed_days}d)")
                continue
        else:  # unregistered
            if unreg_days <= 0:
                n_kept["unregistered_disabled"] += 1
                if verbose:
                    print(f"  KEEP {slug_dir.name}  (unregistered, threshold disabled)")
                continue
            if age < unreg_days:
                n_kept["unregistered_young"] += 1
                if verbose:
                    print(f"  KEEP {slug_dir.name}  (unregistered, age={age:.1f}d < {unreg_days}d)")
                continue
        # prune
        size_mb = sum(f.stat().st_size for f in slug_dir.rglob("*") if f.is_file()) / 1024.0 / 1024.0
        action = "DRY" if dry_run else "RM "
        print(f"  {action} {slug_dir.name}  ({cat}, age={age:.1f}d, {size_mb:.1f}MB)")
        if not dry_run:
            shutil.rmtree(slug_dir)
        n_removed += 1
    print(f"[prune_probe] {'would remove' if dry_run else 'removed'}: {n_removed}  "
          f"kept: {sum(n_kept.values())}  "
          f"({', '.join(f'{k}={v}' for k, v in n_kept.items() if v)})")
    return n_removed


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--yes", action="store_true", help="실제 삭제 (없으면 dry-run)")
    p.add_argument("--dry-run", action="store_true", help="명시적 dry-run (--yes 없으면 기본)")
    p.add_argument("--verbose", action="store_true", help="보존 사유까지 출력")
    args = p.parse_args(argv)
    dry = not args.yes or args.dry_run
    prune(dry_run=dry, verbose=args.verbose)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
