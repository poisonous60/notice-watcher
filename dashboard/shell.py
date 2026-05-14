"""subprocess helper. Windows asyncio 호환 (`SelectorEventLoop` 가 subprocess 미지원이라
`asyncio.create_subprocess_exec` 가 `NotImplementedError` 던짐). `subprocess.run` 을 `to_thread` 로 감쌈.

POSIX 도 동일하게 동작 (사실은 dev box 가 Windows 라서 필요한 우회). 핸들러는 여전히 async.
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Optional


def _run_blocking(cmd: list[str], *, cwd: Optional[Path] = None) -> dict:
    p = subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, errors="replace")
    return {"ok": p.returncode == 0, "rc": p.returncode, "output": p.stdout or ""}


async def async_run(cmd: list[str], *, cwd: Optional[Path] = None) -> dict:
    """`subprocess.run` 의 비차단 wrapper. 반환: {ok, rc, output}."""
    return await asyncio.to_thread(_run_blocking, cmd, cwd=cwd)


__all__ = ["async_run"]
