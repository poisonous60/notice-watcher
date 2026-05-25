"""chromium(Playwright)을 띄우는 작업끼리 동시에 안 돌게 하는 프로세스 간 파일 락.

register.py(probe) 와 poll.py(재-probe / playwright_html·handwritten 사이트 폴링) 가 동시에 chromium 을
띄우면 메모리 폭주 위험이 있어서 — 둘 다 띄우기 직전에 이 락을 잡는다.

`slots>=2` 면 multi-slot 모드 — `.chromium.{0..slots-1}.lock` 파일 N개 중 *첫 번째로 잡히는 것* 을 선택.
worker_pool + poll_cron 의 chromium 사이트 polling 동시 진입 시 슬롯 N개 한도 안에서 capacity limit.
caller 가 매 호출마다 같은 N 값을 줘야 일관 — 봇/폴링 둘 다 `settings.chromium_lock.slots` 에서 읽음.

ADR 0019 Phase 1 — `chromium_lock_async` 비동기 context manager 도 노출. `scripts/poll.py` cron 폴링이
chromium 사이트 fetch 직전 `chromium_lock_async(slots=settings.chromium_lock.slots)` 잡음 → worker
(register/reprobe) 와 같은 N 슬롯 공유. RAM cap = N chromium 바이너리/컨텍스트. event loop 안 막으려고
acquire/release 를 executor thread 로 위임.

쓰는 쪽:
    # sync (register, bot worker)
    from scripts._chromium_lock import chromium_lock
    with chromium_lock(slots=N):     # 다른 caller 가 모든 슬롯 잡고 있으면 풀릴 때까지 대기
        subprocess.run([... register.py ...])

    # async (poll cron)
    from scripts._chromium_lock import chromium_lock_async
    async with chromium_lock_async(timeout=300.0, slots=settings.chromium_lock.slots):
        await adapter.fetch_list(...)

Linux/macOS 는 fcntl.flock, Windows(개발 박스)에서는 no-op (배포 대상은 Linux).
"""
from __future__ import annotations

import contextlib
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Iterator

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


@dataclass
class _AcquiredLock:
    """Internal handle for held flock. `held_fd is None` 가능 = Windows no-op."""
    fds: list[int] = field(default_factory=list)
    held_fd: int | None = None


def _acquire_blocking(*, timeout: float, poll_interval: float, slots: int) -> _AcquiredLock:
    """chromium 작업 전용 배타 락 잡기 (blocking). timeout(초) 안에 못 잡으면 TimeoutError.

    slots>=2 면 multi-file flock — N개 슬롯 파일 중 첫 번째 비어있는 슬롯을 LOCK_NB 로 잡음.
    매 poll_interval 마다 N개 슬롯 다시 try → 하나라도 비면 즉시 진입.
    Windows 는 no-op — 빈 핸들 반환 (TimeoutError 안 남).
    """
    _LOCK_DIR.mkdir(parents=True, exist_ok=True)
    if not _HAVE_FCNTL:
        # Windows 개발 박스 — 락 없이 진행 (동시 실행 안 한다는 가정)
        return _AcquiredLock()
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
        return _AcquiredLock(fds=fds, held_fd=held_fd)
    except BaseException:
        # acquire 실패 (TimeoutError 포함) 시 fd 누수 차단. raise 그대로 전파.
        for fd in fds:
            try:
                os.close(fd)
            except OSError:
                pass
        raise


def _release_blocking(lock: _AcquiredLock) -> None:
    """`_acquire_blocking` 으로 잡은 락 해제 + fd 닫기. Windows no-op 핸들도 안전."""
    if not _HAVE_FCNTL:
        return
    if lock.held_fd is not None:
        try:
            fcntl.flock(lock.held_fd, fcntl.LOCK_UN)
        except OSError:
            pass
    for fd in lock.fds:
        try:
            os.close(fd)
        except OSError:
            pass


@contextlib.contextmanager
def chromium_lock(*, timeout: float = 900.0, poll_interval: float = 1.0,
                  slots: int = 1) -> Iterator[None]:
    """chromium 작업 전용 배타 락. timeout(초) 안에 못 잡으면 TimeoutError.

    slots>=2 면 multi-file flock — N개 슬롯 파일 중 첫 번째 비어있는 슬롯을 LOCK_NB 로 잡음.
    매 poll_interval 마다 N개 슬롯 다시 try → 하나라도 비면 즉시 진입.
    """
    lock = _acquire_blocking(timeout=timeout, poll_interval=poll_interval, slots=slots)
    try:
        yield
    finally:
        _release_blocking(lock)


@contextlib.asynccontextmanager
async def chromium_lock_async(*, timeout: float = 300.0, poll_interval: float = 0.5,
                              slots: int = 1) -> AsyncIterator[None]:
    """chromium_lock 의 async wrapper. acquire/release 를 executor thread 로 위임해 event loop 안 막음.

    ADR 0019 Phase 1 — `scripts/poll.py` cron 폴링의 chromium 사이트 fetch 가 register subprocess 와
    같은 flock 공유. acquire 가 blocking 이라 raw `chromium_lock(...)` 를 async 안에서 쓰면
    event loop 가 멈춰 다른 사이트의 httpx fetch 도 같이 stall. executor 로 위임해 격리.

    cancellation 안전: acquire/release 모두 `asyncio.shield` 로 감싼다. caller 가 cancel 돼도
    executor thread 가 acquire 완료 후 lock 잡힌 채로 leak 되는 걸 막음 — cancel 도착 시 acquire
    완료 대기 후 release. release 도 shield — cancel 중간에 끊겨 lock 남는 일 X.
    codex Phase 1 review HIGH (2026-05-25).
    """
    import asyncio
    loop = asyncio.get_running_loop()
    acquire_fut = loop.run_in_executor(
        None,
        lambda: _acquire_blocking(timeout=timeout, poll_interval=poll_interval, slots=slots),
    )
    try:
        lock = await asyncio.shield(acquire_fut)
    except asyncio.CancelledError:
        # cancel 도착 — executor 안 acquire 는 그대로 진행 중일 수 있다. 완료 후 lock 잡혔으면
        # 즉시 release 해서 leak 방지. add_done_callback 이 fut 결과를 background 에서 처리.
        def _drain_and_release(f: "asyncio.Future") -> None:
            try:
                got = f.result()
            except BaseException:
                return
            try:
                _release_blocking(got)
            except Exception:
                pass
        if acquire_fut.done():
            _drain_and_release(acquire_fut)
        else:
            acquire_fut.add_done_callback(_drain_and_release)
        raise
    try:
        yield
    finally:
        # release 도 shield — cancel 중간에 끊겨 lock 영구 보유 차단.
        release_fut = loop.run_in_executor(None, _release_blocking, lock)
        try:
            await asyncio.shield(release_fut)
        except asyncio.CancelledError:
            # release 는 background 에서 마저 — 어차피 짧음 (flock unlock + close fd).
            raise
