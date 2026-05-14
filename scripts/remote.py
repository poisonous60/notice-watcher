"""N100 원격 명령 실행 CLI. allowlist 강제 — 임의 명령 X.

사용:
    python scripts/remote.py poll-now              # 폴링 즉시 1회 실행
    python scripts/remote.py restart-bot           # Discord 봇 재시작
    python scripts/remote.py status [unit]         # systemctl status
    python scripts/remote.py logs bot --tail 200   # journalctl
    python scripts/remote.py logs poll --tail 100
    python scripts/remote.py daemon-reload         # 유닛 변경 후
    python scripts/remote.py read routing          # 원격 파일 cat (allowlist)
    python scripts/remote.py list                  # 허용 명령 출력

dashboard 가 subprocess 로 호출. stdout 그대로 캡처해 토스트/박스에 표시.

설계:
- 명령은 ACTIONS dict 의 enum (SSH command injection 차단). 사용자 인자는 정해진 알리아스만 매핑.
- DEPLOY_HOST 는 env 로만 받음 (인자로 호스트 받으면 위험).
- 결과 코드: SSH 종료 코드 그대로 전파 (0=성공). stdout 만 print.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import Optional


DEPLOY_HOST = os.environ.get("DEPLOY_HOST", "aaaa@<lan-ip>")
DEPLOY_PATH_RAW = os.environ.get("DEPLOY_PATH", "~/notice-watcher")


# unit alias → 실제 systemd 유닛명
UNITS: dict[str, str] = {
    "bot": "notice-bot.service",
    "poll": "notice-poll.service",
    "poll-timer": "notice-poll.timer",
    "notify": "notice-notify.service",
    "notify-timer": "notice-notify.timer",
}


# read alias → 원격 파일 (allowlist — cat 대상)
READABLE: dict[str, str] = {
    "routing":  f"{DEPLOY_PATH_RAW}/output/llm_routing.json",
    "runtime":  f"{DEPLOY_PATH_RAW}/config.local.toml",
    "prices":   f"{DEPLOY_PATH_RAW}/model_prices.json",
    "env":      f"{DEPLOY_PATH_RAW}/.env",
    "timer":    "~/.config/systemd/user/notice-poll.timer",
    "config-toml": f"{DEPLOY_PATH_RAW}/config.toml",
}


def _ssh(remote_cmd: str) -> int:
    p = subprocess.run(["ssh", DEPLOY_HOST, remote_cmd], capture_output=True, text=True, errors="replace")
    if p.stdout:
        sys.stdout.write(p.stdout)
    if p.stderr:
        sys.stderr.write(p.stderr)
    return p.returncode


def _resolve_unit(alias: str) -> str:
    if alias not in UNITS:
        print(f"[remote] 알 수 없는 unit alias: {alias!r}. 허용: {sorted(UNITS)}", file=sys.stderr)
        sys.exit(4)
    return UNITS[alias]


def cmd_poll_now() -> int:
    return _ssh("systemctl --user start notice-poll.service")


def cmd_restart_bot() -> int:
    return _ssh("systemctl --user restart notice-bot.service")


def cmd_status(alias: str = "bot") -> int:
    u = _resolve_unit(alias)
    return _ssh(f"systemctl --user status {u} --no-pager -n 20")


def cmd_logs(alias: str, tail: int) -> int:
    u = _resolve_unit(alias)
    return _ssh(f"journalctl --user -u {u} -n {int(tail)} --no-pager")


def cmd_daemon_reload() -> int:
    return _ssh("systemctl --user daemon-reload")


def cmd_read(alias: str) -> int:
    if alias not in READABLE:
        print(f"[remote] 알 수 없는 read alias: {alias!r}. 허용: {sorted(READABLE)}", file=sys.stderr)
        return 4
    path = READABLE[alias]
    # `cat` 만 — 쓰기/실행 권한 X. path 는 DEPLOY_PATH env 가 섞일 수 있어 single-quote 로 감쌈
    # (shell metachar 차단). path 자체에 single quote 가 있으면 안전 분해.
    safe_path = "'" + path.replace("'", "'\\''") + "'"
    return _ssh(f"cat {safe_path}")


def list_actions() -> int:
    print("commands:")
    print("  poll-now                    notice-poll.service 즉시 실행")
    print("  restart-bot                 notice-bot.service 재시작")
    print("  status [unit]               systemctl --user status (default: bot)")
    print("  logs <unit> [--tail N]      journalctl --user -u")
    print("  daemon-reload               systemctl --user daemon-reload")
    print("  read <alias>                원격 파일 cat (allowlist)")
    print()
    print(f"unit aliases: {', '.join(sorted(UNITS))}")
    print(f"read aliases: {', '.join(sorted(READABLE))}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="N100 원격 명령 (allowlist)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("poll-now")
    sub.add_parser("restart-bot")
    sp = sub.add_parser("status"); sp.add_argument("unit", nargs="?", default="bot")
    sp = sub.add_parser("logs"); sp.add_argument("unit"); sp.add_argument("--tail", type=int, default=100)
    sub.add_parser("daemon-reload")
    sp = sub.add_parser("read"); sp.add_argument("alias")
    sub.add_parser("list")
    args = p.parse_args(argv)
    if args.cmd == "list":
        return list_actions()
    if args.cmd == "poll-now":
        return cmd_poll_now()
    if args.cmd == "restart-bot":
        return cmd_restart_bot()
    if args.cmd == "status":
        return cmd_status(args.unit)
    if args.cmd == "logs":
        return cmd_logs(args.unit, args.tail)
    if args.cmd == "daemon-reload":
        return cmd_daemon_reload()
    if args.cmd == "read":
        return cmd_read(args.alias)
    print(f"[remote] unknown cmd {args.cmd!r}", file=sys.stderr)
    return 4


if __name__ == "__main__":
    sys.exit(main())
