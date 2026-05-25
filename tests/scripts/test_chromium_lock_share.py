"""ADR 0019 Phase 1 — cross-process flock serialization 검증.

두 child process 가 같은 lock file 을 race — 정상이면 mutex 보장 (non-overlap).
Linux/macOS 만 — Windows 는 fcntl 없어 _chromium_lock 이 no-op 라 mutex 없음 → skip.

실행: `python tests/scripts/test_chromium_lock_share.py` (프로젝트 컨벤션 — pytest 안 씀).
"""
from __future__ import annotations

import multiprocessing as mp
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    import fcntl  # noqa: F401 — Windows = ImportError
    _HAVE_FCNTL = True
except ImportError:
    _HAVE_FCNTL = False


def _child_acquire_hold_release(lock_dir: str, record_path: str, name: str,
                                 hold_s: float, timeout_s: float) -> None:
    """child process — lock 잡고 hold_s 만큼 sleep 후 release. (start_t, end_t, name) tsv 한 줄."""
    from pathlib import Path as _P
    from scripts import _chromium_lock
    _chromium_lock._LOCK_DIR = _P(lock_dir)
    _chromium_lock._LEGACY_LOCK_PATH = _P(lock_dir) / ".chromium.lock"

    try:
        lock = _chromium_lock._acquire_blocking(
            timeout=timeout_s, poll_interval=0.05, slots=1,
        )
        t_acq = time.monotonic()
        time.sleep(hold_s)
        t_rel = time.monotonic()
        _chromium_lock._release_blocking(lock)
    except Exception as e:  # noqa: BLE001
        with open(record_path, "a", encoding="utf-8") as f:
            f.write(f"{name}\tERROR\t{type(e).__name__}: {e}\n")
        raise SystemExit(1)
    with open(record_path, "a", encoding="utf-8") as f:
        f.write(f"{name}\t{t_acq:.6f}\t{t_rel:.6f}\n")


def _test_two_processes_serialize() -> tuple[str, bool, str]:
    """두 process 가 같은 chromium_lock 을 race — 두 acquire 구간이 안 겹치는지."""
    if not _HAVE_FCNTL:
        return ("two_processes_serialize", True, "SKIP — fcntl 없음 (Windows)")
    tmp = Path(tempfile.mkdtemp(prefix="chromium_lock_test_"))
    record = tmp / "events.tsv"
    record.write_text("", encoding="utf-8")
    ctx = mp.get_context("fork")
    hold = 0.4
    p1 = ctx.Process(target=_child_acquire_hold_release,
                     args=(str(tmp), str(record), "A", hold, 10.0))
    p2 = ctx.Process(target=_child_acquire_hold_release,
                     args=(str(tmp), str(record), "B", hold, 10.0))
    p1.start()
    time.sleep(0.05)  # B 가 1번째 race 진입 못 하게 stagger
    p2.start()
    p1.join(timeout=15)
    p2.join(timeout=15)
    if p1.exitcode != 0:
        return ("two_processes_serialize", False, f"A child failed: {record.read_text()}")
    if p2.exitcode != 0:
        return ("two_processes_serialize", False, f"B child failed: {record.read_text()}")
    rows = [line.split("\t") for line in record.read_text(encoding="utf-8").strip().splitlines()]
    if len(rows) != 2:
        return ("two_processes_serialize", False, f"expected 2 rows, got {rows!r}")
    intervals = sorted(((float(t_acq), float(t_rel), name) for name, t_acq, t_rel in rows),
                       key=lambda x: x[0])
    first_end = intervals[0][1]
    second_start = intervals[1][0]
    epsilon = 0.02
    if second_start + epsilon < first_end:
        return ("two_processes_serialize", False,
                f"직렬화 실패 — first=({intervals[0][0]:.3f},{intervals[0][1]:.3f}), "
                f"second=({intervals[1][0]:.3f},{intervals[1][1]:.3f})")
    return ("two_processes_serialize", True,
            f"mutex OK — first.end={first_end:.3f}, second.start={second_start:.3f}")


def _test_acquire_timeout_when_held() -> tuple[str, bool, str]:
    """다른 process 가 hold 중일 때 acquire timeout — TimeoutError 발생 확인."""
    if not _HAVE_FCNTL:
        return ("acquire_timeout_when_held", True, "SKIP — fcntl 없음 (Windows)")
    tmp = Path(tempfile.mkdtemp(prefix="chromium_lock_timeout_"))
    record = tmp / "events.tsv"
    record.write_text("", encoding="utf-8")
    ctx = mp.get_context("fork")
    holder = ctx.Process(target=_child_acquire_hold_release,
                         args=(str(tmp), str(record), "HOLDER", 1.0, 5.0))
    holder.start()
    time.sleep(0.1)  # holder lock 잡을 시간

    # main process 에서 acquire 시도 — patched _LOCK_DIR. 다른 child 의 lock 과 같은 path 라 conflict.
    from scripts import _chromium_lock
    saved_dir = _chromium_lock._LOCK_DIR
    saved_legacy = _chromium_lock._LEGACY_LOCK_PATH
    _chromium_lock._LOCK_DIR = tmp
    _chromium_lock._LEGACY_LOCK_PATH = tmp / ".chromium.lock"
    try:
        _chromium_lock._acquire_blocking(timeout=0.2, poll_interval=0.05, slots=1)
        holder.join(timeout=5)
        return ("acquire_timeout_when_held", False,
                "기대 = TimeoutError, 실제 = acquire 성공")
    except TimeoutError:
        holder.join(timeout=5)
        if holder.exitcode != 0:
            return ("acquire_timeout_when_held", False,
                    f"holder failed: {record.read_text()}")
        return ("acquire_timeout_when_held", True, "TimeoutError 정상 발생")
    finally:
        _chromium_lock._LOCK_DIR = saved_dir
        _chromium_lock._LEGACY_LOCK_PATH = saved_legacy


def run() -> list[tuple[str, bool, str]]:
    return [
        _test_two_processes_serialize(),
        _test_acquire_timeout_when_held(),
    ]


if __name__ == "__main__":
    results = run()
    failed = [(n, d) for n, ok, d in results if not ok]
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {d}")
    if failed:
        print(f"\n{len(failed)} FAILED")
        sys.exit(1)
    print(f"\n{len(results)} passed")
