"""subprocess helper. Windows asyncio 호환 (`SelectorEventLoop` 가 subprocess 미지원이라
`asyncio.create_subprocess_exec` 가 `NotImplementedError` 던짐). `subprocess.run` 을 `to_thread` 로 감쌈.

POSIX 도 동일하게 동작 (사실은 dev box 가 Windows 라서 필요한 우회). 핸들러는 여전히 async.

tracing: TRACE_ENABLED=1 이면 dev박스 쪽에서 outer span 1개 기록 (SSH overhead + N100 작업 합).
remote.py 의 verb 들 중 N100 측 helper 가 inner trace 를 만드는 verb (poll-now-slug,
notify-target, …) 면 env_for_child() 가 자식 process 로 trace_id 전달 → 같은 trace 안에서
N100 spans 가 inner 로 붙음.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path
from typing import Optional

from engine.tracing import is_enabled, start_trace, env_for_child, current_trace


def _run_blocking(cmd: list[str], *, cwd: Optional[Path] = None,
                   env: Optional[dict] = None) -> dict:
    p = subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, errors="replace", env=env)
    return {"ok": p.returncode == 0, "rc": p.returncode, "output": p.stdout or ""}


def _verb_for_label(cmd: list[str]) -> str:
    """`python scripts/remote.py poll-now-slug …` → "ssh_call.poll-now-slug" 라벨."""
    try:
        # cmd[0] = python, cmd[1] = remote.py path, cmd[2] = verb
        if len(cmd) >= 3 and cmd[1].endswith("remote.py"):
            return f"ssh_call.{cmd[2]}"
        return f"shell.{Path(cmd[1]).name if len(cmd) > 1 else 'cmd'}"
    except Exception:  # noqa: BLE001
        return "shell.cmd"


async def async_run(cmd: list[str], *, cwd: Optional[Path] = None) -> dict:
    """`subprocess.run` 의 비차단 wrapper. 반환: {ok, rc, output}.

    TRACE_ENABLED=1: dev박스에서 outer trace + span 자동 wrap. trace 이미 있으면 span 만 추가.
    """
    if not is_enabled():
        return await asyncio.to_thread(_run_blocking, cmd, cwd=cwd)

    label = _verb_for_label(cmd)
    parent = current_trace()
    if parent is None:
        # dashboard 호출 1건 = 1 trace. ssh_call.<verb> span 안에서 child env 전달.
        with start_trace("dashboard", attrs={"cmd": label}) as tr:
            with tr.span(label, attrs={"cmd_argv": " ".join(cmd[:4])}):
                env = {**os.environ, **env_for_child()}
                return await asyncio.to_thread(_run_blocking, cmd, cwd=cwd, env=env)
    else:
        with parent.span(label, attrs={"cmd_argv": " ".join(cmd[:4])}):
            env = {**os.environ, **env_for_child()}
            return await asyncio.to_thread(_run_blocking, cmd, cwd=cwd, env=env)


__all__ = ["async_run"]
