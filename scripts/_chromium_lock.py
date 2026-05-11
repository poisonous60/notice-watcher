"""chromium(Playwright)을 띄우는 작업끼리 동시에 안 돌게 하는 프로세스 간 파일 락.

register.py(probe) 와 poll.py(재-probe / playwright_html·handwritten 사이트 폴링) 가 동시에 chromium 을
띄우면 메모리(특히 1GB 급 박스)가 터질 수 있어서 — 둘 다 띄우기 직전에 이 락을 잡는다.

쓰는 쪽:
    from scripts._chromium_lock import chromium_lock
    with chromium_lock():            # 다른 쪽이 잡고 있으면 풀릴 때까지 대기
        subprocess.run([... register.py ...])

Linux/macOS 는 fcntl.flock, Windows(개발 박스)에서는 no-op (배포 대상은 Linux).
"""
from __future__ import annotations

import contextlib
import os
import time
from pathlib import Path
from typing import Iterator

_LOCK_PATH = Path(__file__).resolve().parent.parent / "output" / ".chromium.lock"

try:
    import fcntl  # type: ignore

    _HAVE_FCNTL = True
except ImportError:  # Windows
    _HAVE_FCNTL = False


@contextlib.contextmanager
def chromium_lock(*, timeout: float = 900.0, poll_interval: float = 1.0) -> Iterator[None]:
    """chromium 작업 전용 배타 락. timeout(초) 안에 못 잡으면 TimeoutError."""
    _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not _HAVE_FCNTL:
        # Windows 개발 박스 — 락 없이 진행 (동시 실행 안 한다는 가정)
        yield
        return
    fd = os.open(str(_LOCK_PATH), os.O_CREAT | os.O_RDWR, 0o644)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"chromium 락 획득 실패 ({timeout}s 대기) — {_LOCK_PATH}")
                time.sleep(poll_interval)
        try:
            os.ftruncate(fd, 0)
            os.write(fd, f"{os.getpid()}\n".encode())
        except OSError:
            pass
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)
