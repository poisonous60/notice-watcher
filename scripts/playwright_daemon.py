"""Chromium 데몬 — probe 의 cold launch (~2-3s) 회피.

chromium 을 `--remote-debugging-port=N` 으로 띄워두고 CDP endpoint 노출.
probe 는 `playwright.chromium.connect_over_cdp(endpoint)` 로 attach → launch 안 함.

(Python sync_api 에는 `launch_server` 가 없음 — Node.js 전용. CDP 방식이 sync_api 호환.)

수동 사용:
    python scripts/playwright_daemon.py           # 시작 (foreground)
    python scripts/playwright_daemon.py status    # 상태
    python scripts/playwright_daemon.py stop      # graceful stop (STOP_FLAG)

Linux background:
    nohup python scripts/playwright_daemon.py start >/dev/null 2>&1 &
    # 또는: setsid python scripts/playwright_daemon.py start &
Windows background (PowerShell):
    Start-Process python -ArgumentList "scripts/playwright_daemon.py","start" -WindowStyle Hidden

protocol (output/playwright_daemon/ 디렉토리):
- endpoint     : "http://127.0.0.1:NNNN" (CDP endpoint)
- pid          : 데몬 PID
- daemon.log   : 로그

idle 정책: 매 POLL_INTERVAL_S 마다 endpoint 파일 mtime 검사 → IDLE_TIMEOUT_S 미갱신이면 자기 자신 stop.
probe 가 connect 시 endpoint 파일 touch → idle 타이머 reset.

N100 적용 안 함 (RAM 1-2GB 제약). dev 박스에서만 띄움.
endpoint 파일 없으면 probe 는 기존대로 fresh launch — backwards-compatible.
"""
from __future__ import annotations

import argparse
import os
import signal
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DAEMON_DIR = ROOT / "output" / "playwright_daemon"
ENDPOINT_FILE = DAEMON_DIR / "endpoint"
PID_FILE = DAEMON_DIR / "pid"
CHROME_PID_FILE = DAEMON_DIR / "chrome_pid"   # orphan chromium 회수용
STOP_FLAG = DAEMON_DIR / "stop"               # Windows graceful stop 신호
LOG_FILE = DAEMON_DIR / "daemon.log"

IDLE_TIMEOUT_S = 600.0    # 10분 idle 면 self-stop
POLL_INTERVAL_S = 5.0     # mtime + stop flag + chromium liveness 확인 주기 (Windows graceful stop 반응시간)

# fetch_headless._LAUNCH_ARGS 와 동기화 — daemon 도 같은 chromium 가속 args 로 띄움.
_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-default-apps",
    "--disable-extensions",
    "--disable-component-extensions-with-background-pages",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-features=TranslateUI",
    "--disable-translate",
]


def _log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line, flush=True)


def _read_pid_file(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None


def _read_pid() -> int | None:
    return _read_pid_file(PID_FILE)


def _is_pid_alive(pid: int) -> bool:
    """signal 0 으로 살아있는지 확인.

    PermissionError = "프로세스 존재하지만 권한 없어 못 봄" → 살아있음으로 보수적 판정 (이중 spawn 방지).
    ProcessLookupError(ESRCH) = "PID 없음" → 죽음. Windows 도 동작 동일.
    """
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # 권한 없어 못 봤지만 PID 자체는 살아있음
        return True
    except OSError:
        return False


def _kill_orphan_chrome() -> None:
    """stale chrome_pid 파일에 적힌 PID 가 살아있으면 SIGTERM. 이전 daemon 이 SIGKILL 등으로
    죽었을 때 chromium 만 orphan 으로 살아남는 케이스 처리.

    POSIX 에선 chromium 이 별도 process group (start_new_session=True) 이라 SIGKILL escalation 시
    `os.killpg` 로 renderer/GPU child 까지 정리. Windows 는 chromium 단일 PID 만 처리.
    """
    chrome_pid = _read_pid_file(CHROME_PID_FILE)
    if chrome_pid is None:
        return
    if not _is_pid_alive(chrome_pid):
        CHROME_PID_FILE.unlink(missing_ok=True)
        return
    try:
        # POSIX: 가능하면 process group 전체로 보냄
        if os.name == "posix":
            try:
                pgid = os.getpgid(chrome_pid)
                os.killpg(pgid, signal.SIGTERM)
                _log(f"orphan chromium killpg(SIGTERM): pgid={pgid}")
            except (ProcessLookupError, PermissionError, OSError):
                # pgid 못 얻거나 권한 없으면 단일 PID 로 fallback
                os.kill(chrome_pid, signal.SIGTERM)
                _log(f"orphan chromium kill(SIGTERM): pid={chrome_pid}")
        else:
            os.kill(chrome_pid, signal.SIGTERM)
            _log(f"orphan chromium kill: pid={chrome_pid}")
        # 짧게 wait — 안 죽으면 SIGKILL (POSIX 만 — Windows SIGTERM = TerminateProcess 즉사)
        for _ in range(20):  # 2s
            if not _is_pid_alive(chrome_pid):
                break
            time.sleep(0.1)
        if _is_pid_alive(chrome_pid) and os.name == "posix":
            try:
                try:
                    pgid = os.getpgid(chrome_pid)
                    os.killpg(pgid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    os.kill(chrome_pid, signal.SIGKILL)
            except (AttributeError, OSError):
                pass
    except OSError as e:
        _log(f"orphan chromium kill fail: {e}")
    CHROME_PID_FILE.unlink(missing_ok=True)


def cmd_status() -> int:
    pid = _read_pid()
    alive = pid is not None and _is_pid_alive(pid)
    if alive and ENDPOINT_FILE.exists():
        endpoint = ENDPOINT_FILE.read_text(encoding="utf-8").strip()
        idle_s = time.time() - ENDPOINT_FILE.stat().st_mtime
        print(f"[playwright_daemon] running pid={pid} idle={idle_s:.0f}s endpoint={endpoint}")
        return 0
    print("[playwright_daemon] not running")
    return 1


def cmd_stop() -> int:
    pid = _read_pid()
    if pid is None:
        print("[playwright_daemon] no pid file")
        # orphan chromium 있을 수 있음 — 청소
        _kill_orphan_chrome()
        return 1
    if not _is_pid_alive(pid):
        print(f"[playwright_daemon] pid {pid} not alive — cleaning stale + orphan chromium")
        _kill_orphan_chrome()
        PID_FILE.unlink(missing_ok=True)
        ENDPOINT_FILE.unlink(missing_ok=True)
        STOP_FLAG.unlink(missing_ok=True)
        return 0
    # Windows 에서 os.kill(pid, SIGTERM) = TerminateProcess → finally 안 돌아 chromium orphan.
    # graceful stop: STOP_FLAG 파일 생성, daemon 루프가 감지해 정리하고 자기 종료.
    try:
        DAEMON_DIR.mkdir(parents=True, exist_ok=True)
        STOP_FLAG.write_text("stop", encoding="utf-8")
        print(f"[playwright_daemon] stop flag set → pid {pid} (graceful)")
    except OSError as e:
        print(f"[playwright_daemon] stop flag write fail: {e}")
        return 1
    # 짧게 대기 후 살아있으면 SIGTERM fallback (POSIX 만 의미 — Windows 는 즉사)
    for _ in range(40):  # 20s 까지 graceful
        if not _is_pid_alive(pid):
            return 0
        time.sleep(0.5)
    print(f"[playwright_daemon] graceful stop timeout, fallback SIGTERM → pid {pid}")
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as e:
        print(f"[playwright_daemon] SIGTERM fail: {e}")
        return 1
    return 0


def cmd_start() -> int:
    DAEMON_DIR.mkdir(parents=True, exist_ok=True)

    existing = _read_pid()
    if existing is not None and _is_pid_alive(existing):
        _log(f"already running (pid={existing}) — exit")
        return 0
    # stale PID 청소 — orphan chromium 있으면 함께 kill (이전 daemon 이 SIGKILL/OOM 으로 죽은 케이스)
    _kill_orphan_chrome()
    PID_FILE.unlink(missing_ok=True)
    ENDPOINT_FILE.unlink(missing_ok=True)
    STOP_FLAG.unlink(missing_ok=True)
    # stale userdata_* 디렉터리 청소 — SIGKILL/OOM 으로 죽은 이전 daemon 들의 잔여물 누적 방지.
    # PID 재사용으로 동일 suffix 의 오염된 dir 받아쓰는 위험도 차단.
    import shutil as _shutil_pre
    for _d in DAEMON_DIR.glob("userdata_*"):
        try:
            _shutil_pre.rmtree(_d, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass

    # O_EXCL 로 PID file 원자 생성 — 동시 cmd_start 들이 race 못 함. 패자는 즉시 exit.
    try:
        fd = os.open(str(PID_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        _log("PID file 동시 생성 race — 다른 daemon 이 이김, exit")
        return 0
    try:
        os.write(fd, str(os.getpid()).encode())
    finally:
        os.close(fd)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _log("playwright not installed")
        PID_FILE.unlink(missing_ok=True)
        return 2

    # Playwright 의 launch() 가 띄운 chromium 은 자체 IPC pipe 만 씀 → `--remote-debugging-port` 무시,
    # 외부 connect_over_cdp 불가. 그래서 chromium binary path 만 받아서 직접 subprocess.Popen 으로 띄움.
    import subprocess as _sp
    with sync_playwright() as _p_tmp:
        chrome_path = _p_tmp.chromium.executable_path
    if not chrome_path or not Path(chrome_path).exists():
        _log(f"chromium binary not found: {chrome_path!r}")
        PID_FILE.unlink(missing_ok=True)
        return 3

    # 빈 포트 잡기
    _s = socket.socket()
    _s.bind(("127.0.0.1", 0))
    port = _s.getsockname()[1]
    _s.close()

    # repo-local + PID suffix — 동시 daemon 실수로 띄워졌을 때도 userdata 안 겹침.
    # output/ 은 .gitignore.
    userdata = DAEMON_DIR / f"userdata_{os.getpid()}"
    userdata.mkdir(parents=True, exist_ok=True)

    chrome_args = [
        chrome_path,
        f"--remote-debugging-port={port}",
        "--headless=new",
        f"--user-data-dir={userdata}",
        "--remote-allow-origins=*",
        *_LAUNCH_ARGS,
        "about:blank",
    ]

    stopping = False

    def _on_signal(signum, _frame):
        nonlocal stopping
        _log(f"signal {signum} — stop")
        stopping = True

    for s in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(s, _on_signal)
        except (ValueError, OSError):
            # Windows 일부 환경에서 핸들 못 잡을 수 있음 — 무시
            pass

    _log(f"spawning chromium: {chrome_path} (port={port})")
    # start_new_session (POSIX) — chromium 을 별도 process group 으로 → SIGKILL escalation 시
    # os.killpg 로 renderer/GPU child 까지 함께 정리. Windows 는 무시됨.
    _popen_kwargs = dict(
        stdin=_sp.DEVNULL,
        stdout=_sp.DEVNULL,
        stderr=_sp.DEVNULL,
    )
    if os.name == "posix":
        _popen_kwargs["start_new_session"] = True
    chrome_proc = _sp.Popen(chrome_args, **_popen_kwargs)

    # CDP port listen 시작 기다림 (최대 10s)
    endpoint = f"http://127.0.0.1:{port}"
    ready = False
    for _ in range(50):  # 50 × 0.2s = 10s
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                ready = True
                break
        except (OSError, ConnectionRefusedError):
            time.sleep(0.2)
        if chrome_proc.poll() is not None:
            _log(f"chromium 즉시 종료 rc={chrome_proc.returncode}")
            PID_FILE.unlink(missing_ok=True)
            return 4
    if not ready:
        _log("chromium CDP port listen 안 됨 — 종료")
        chrome_proc.terminate()
        PID_FILE.unlink(missing_ok=True)
        return 5

    ENDPOINT_FILE.write_text(endpoint, encoding="utf-8")
    CHROME_PID_FILE.write_text(str(chrome_proc.pid), encoding="utf-8")
    _log(f"start pid={os.getpid()} chrome_pid={chrome_proc.pid} endpoint={endpoint}")

    try:
        while not stopping:
            time.sleep(POLL_INTERVAL_S)
            # Windows 의 SIGTERM 핸들러는 즉사라 신호 못 받음 → STOP_FLAG 파일 기반 graceful stop
            if STOP_FLAG.exists():
                _log("STOP_FLAG 감지 — stop")
                break
            if chrome_proc.poll() is not None:
                _log(f"chromium 죽음 rc={chrome_proc.returncode} — stop")
                break
            try:
                last_use = ENDPOINT_FILE.stat().st_mtime
            except FileNotFoundError:
                _log("endpoint file 사라짐 — stop")
                break
            idle_s = time.time() - last_use
            if idle_s > IDLE_TIMEOUT_S:
                _log(f"idle {idle_s:.0f}s > {IDLE_TIMEOUT_S}s — stop")
                break
    finally:
        try:
            # POSIX: chromium process group 전체에 SIGTERM (renderer/GPU 자식까지)
            if os.name == "posix":
                try:
                    pgid = os.getpgid(chrome_proc.pid)
                    os.killpg(pgid, signal.SIGTERM)
                except (ProcessLookupError, OSError):
                    chrome_proc.terminate()
            else:
                chrome_proc.terminate()
            try:
                chrome_proc.wait(timeout=5)
            except _sp.TimeoutExpired:
                if os.name == "posix":
                    try:
                        pgid = os.getpgid(chrome_proc.pid)
                        os.killpg(pgid, signal.SIGKILL)
                    except (ProcessLookupError, OSError):
                        chrome_proc.kill()
                else:
                    chrome_proc.kill()
                chrome_proc.wait(timeout=3)
        except Exception as e:
            _log(f"chrome.terminate fail: {e}")
        # userdata 디렉토리 정리 — repo-local 이라 PID-suffix 재활용 X
        try:
            import shutil as _shutil
            _shutil.rmtree(userdata, ignore_errors=True)
        except Exception as e:
            _log(f"userdata cleanup fail: {e}")
        ENDPOINT_FILE.unlink(missing_ok=True)
        CHROME_PID_FILE.unlink(missing_ok=True)
        STOP_FLAG.unlink(missing_ok=True)
        PID_FILE.unlink(missing_ok=True)
        _log("stopped")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Playwright chromium daemon")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("start", help="start daemon (foreground)")
    sub.add_parser("stop", help="stop daemon via SIGTERM")
    sub.add_parser("status", help="show daemon status")
    args = ap.parse_args(argv)
    if args.cmd == "stop":
        return cmd_stop()
    if args.cmd == "status":
        return cmd_status()
    return cmd_start()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
