"""chromium(Playwright)을 띄우는 작업끼리 동시에 안 돌게 하는 프로세스 간 파일 락.

register.py(probe) 와 poll.py(재-probe / playwright_html·handwritten 사이트 폴링) 가 동시에 chromium 을
띄우면 메모리 폭주 위험이 있어서 — 둘 다 띄우기 직전에 이 락을 잡는다.

`slots>=2` 면 multi-slot 모드 — `.chromium.{0..slots-1}.lock` 파일 N개 중 *첫 번째로 잡히는 것* 을 선택.
worker_pool=2 + poll_and_notify 동시 시각에 깨는 spike 같은 경우 슬롯 N개 한도 안에서 동시 진입 허용.
caller 가 매 호출마다 같은 N 값을 줘야 일관 — 봇/폴링 둘 다 `settings.chromium_lock.slots` 에서 읽음.

쓰는 쪽:
    from scripts._chromium_lock import chromium_lock
    with chromium_lock(slots=N):     # 다른 caller 가 모든 슬롯 잡고 있으면 풀릴 때까지 대기
        subprocess.run([... register.py ...])

Linux/macOS 는 fcntl.flock, Windows(개발 박스)에서는 no-op (배포 대상은 Linux).
"""
from __future__ import annotations

import contextlib
import os
import random
import time
from pathlib import Path
from typing import Iterator

_LOCK_DIR = Path(__file__).resolve().parent.parent / "output"
# slots=1 backward-compat — 기존 `.chromium.lock` 파일 그대로.
_LEGACY_LOCK_PATH = _LOCK_DIR / ".chromium.lock"

try:
    import fcntl  # type: ignore

    _HAVE_FCNTL = True
except ImportError:  # Windows
    _HAVE_FCNTL = False


def _slot_paths(slots: int) -> list[Path]:
    if slots <= 1:
        return [_LEGACY_LOCK_PATH]
    return [_LOCK_DIR / f".chromium.{i}.lock" for i in range(slots)]


@contextlib.contextmanager
def chromium_lock(*, timeout: float = 900.0, poll_interval: float = 1.0,
                  slots: int = 1) -> Iterator[None]:
    """chromium 작업 전용 배타 락. timeout(초) 안에 못 잡으면 TimeoutError.

    slots>=2 면 multi-file flock — N개 슬롯 파일 중 첫 번째 비어있는 슬롯을 LOCK_NB 로 잡음.
    매 poll_interval 마다 N개 슬롯 다시 try → 하나라도 비면 즉시 진입.
    """
    _LOCK_DIR.mkdir(parents=True, exist_ok=True)
    if not _HAVE_FCNTL:
        # Windows 개발 박스 — 락 없이 진행 (동시 실행 안 한다는 가정)
        yield
        return
    paths = _slot_paths(slots)
    fds: list[int] = []
    held_fd: int | None = None
    try:
        # os.open 도중 EMFILE/EACCES 등으로 raise 하면 이미 연 fd 들이 누수되지 않도록 try 안에서.
        for p in paths:
            fds.append(os.open(str(p), os.O_CREAT | os.O_RDWR, 0o644))
        deadline = time.monotonic() + timeout
        while held_fd is None:
            # 매 retry 마다 시도 순서 셔플 — 같은 슬롯 (특히 0) 만 계속 잡혀 다른 슬롯이
            # 놀고 있는 starvation 회피. caller 가 N 동시 진입 시 부하 골고루 분산.
            order = list(fds)
            random.shuffle(order)
            for fd in order:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    held_fd = fd
                    break
                except OSError:
                    continue
            if held_fd is not None:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError(f"chromium 락 획득 실패 ({timeout}s 대기, slots={slots}) — {_LOCK_DIR}")
            time.sleep(poll_interval)
        try:
            os.ftruncate(held_fd, 0)
            os.write(held_fd, f"{os.getpid()}\n".encode())
        except OSError:
            pass
        yield
    finally:
        if held_fd is not None:
            try:
                fcntl.flock(held_fd, fcntl.LOCK_UN)
            except OSError:
                pass
        for fd in fds:
            try:
                os.close(fd)
            except OSError:
                pass
