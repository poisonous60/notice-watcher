"""실행 환경 캡처 — 같은 사이트를 다른 환경(GoodbyeDPI on/off, VPN 등)에서 재진단할 때 비교용.

Hitomi-Downloader가 GoodbyeDPI를 패키지에 내장한 사실에서 출발: 일부 한국 통신사 SNI 차단된
도메인은 GoodbyeDPI를 켜면 통과한다. 도구 한 번에 토글이 불가능하므로, 환경을 *기록*만 하고
사용자에게 두 번 실행 비교를 안내한다.
"""
from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import sys
from pathlib import Path


_GDPI_PROCESS_NAMES = ("goodbyedpi.exe", "GoodbyeDPI.exe")


def detect_goodbyedpi_running() -> tuple[bool, str]:
    """Windows에서 goodbyedpi 프로세스가 가동 중인지 tasklist로 검사.

    Returns: (running, info)
    """
    if sys.platform != "win32":
        return False, "non-windows"
    try:
        # /FO CSV 로 받아서 검색
        out = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        text = (out.stdout or "")
        for name in _GDPI_PROCESS_NAMES:
            if name.lower() in text.lower():
                return True, f"detected: {name}"
        return False, "not detected"
    except Exception as e:
        return False, f"detect error: {type(e).__name__}: {e}"


def get_outbound_ip_via(target: str = "8.8.8.8") -> str:
    """라우팅 테이블 기준 outbound 인터페이스 IP. 외부 호출 안 함."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect((target, 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "unknown"


def capture(out_dir: Path) -> dict:
    gdpi_running, gdpi_info = detect_goodbyedpi_running()
    info = {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "arch": platform.machine(),
        "outbound_ip_local": get_outbound_ip_via(),
        "goodbyedpi_running": gdpi_running,
        "goodbyedpi_info": gdpi_info,
        "env_proxy": {
            k: v for k, v in os.environ.items()
            if k.upper() in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY")
        },
    }
    (out_dir / "environment.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return info


def gdpi_advice(env: dict) -> list[str]:
    """summary에 넣을 GoodbyeDPI 비교 안내."""
    msgs: list[str] = []
    if env.get("goodbyedpi_running"):
        msgs.append("GoodbyeDPI 가동 중 — DPI 우회 활성 상태로 측정됨. 비교를 위해 GoodbyeDPI를 종료한 뒤 재실행.")
    else:
        msgs.append("GoodbyeDPI 미가동 — 통신사 SNI 차단 영향 여부를 보려면 GoodbyeDPI를 가동한 뒤 재실행.")
    return msgs
