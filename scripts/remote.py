"""N100 원격 명령 실행 CLI. allowlist 강제 — 임의 명령 X.

사용:
    python scripts/remote.py poll-now                                       # 폴링 즉시 1회 실행
    python scripts/remote.py restart-bot                                    # Discord 봇 재시작
    python scripts/remote.py status [unit]                                  # systemctl status
    python scripts/remote.py logs bot --tail 200                            # journalctl
    python scripts/remote.py logs poll --tail 100
    python scripts/remote.py daemon-reload                                  # 유닛 변경 후
    python scripts/remote.py read routing                                   # 원격 파일 cat (allowlist)
    python scripts/remote.py poll-now-slug s1,s2                            # 부분 poll-now (slug 일부만)
    python scripts/remote.py replay-deliveries <slug> <kind> <id> [post]    # M2/M3 replay (lock 잡고 직렬)
    python scripts/remote.py notify-target <slug> <kind> <id>               # collected → 그 target 만 발송
    python scripts/remote.py announce-scoped <base64-json>                  # 좁힌 공지 발송
    python scripts/remote.py list                                           # 허용 명령 출력

dashboard 가 subprocess 로 호출. stdout 그대로 캡처해 토스트/박스에 표시.

설계:
- 명령은 ACTIONS dict 의 enum (SSH command injection 차단). 사용자 인자는 정해진 알리아스만 매핑.
- 자유 입력(slug, target_id, post_id, base64 payload) 은 정규식으로 거른 뒤에만 SSH command 에 interpolation.
- 모든 verb 의 N100 측 실행 = `cd $DEPLOY_PATH && python scripts/<helper>.py …` — 인자는 항상 끝에 append, base64 같은 큰 페이로드도 shell escape 안전 (base64 문자셋 [A-Za-z0-9+/=] 는 metachar 없음).
- DEPLOY_HOST 는 env 로만 받음 (인자로 호스트 받으면 위험).
- 결과 코드: SSH 종료 코드 그대로 전파 (0=성공). stdout 만 print.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from typing import Optional


DEPLOY_HOST = os.environ.get("DEPLOY_HOST", "aaaa@<lan-ip>")
DEPLOY_PATH_RAW = os.environ.get("DEPLOY_PATH", "~/notice-watcher")

# DEPLOY_PATH 가 SSH command 에 직접 interpolation 되므로 안전 문자만 허용. 위반 시 즉시 거부.
# 허용: 영숫자, `_`, `.`, `/`, `-`, `~`, `$` (예: `~/notice-watcher`, `$HOME/foo`).
_DEPLOY_PATH_RE = re.compile(r"^[A-Za-z0-9_./~$-]+$")
if not _DEPLOY_PATH_RE.match(DEPLOY_PATH_RAW):
    raise SystemExit(f"[remote] DEPLOY_PATH unsafe characters: {DEPLOY_PATH_RAW!r}")

# 자유 입력 인자 validation — interpolation 전 거름.
_SLUG_RE = re.compile(r"^[A-Za-z0-9._%\-]{1,200}$")           # engine.slug 형식 — `%` 포함(URL-encoded UTF-8 seg)
_TARGET_ID_RE = re.compile(r"^[0-9]{1,32}$")                    # Discord snowflake (현재 19자리, 미래 여유)
_POST_ID_RE = re.compile(r"^[\w\-./:%]{1,128}$")               # poll.py 의 _STABLE_ID_RE 와 동일
_BASE64_RE = re.compile(r"^[A-Za-z0-9+/=]{1,200000}$")         # base64 문자셋만; ≤200KB 페이로드
_TRACE_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")          # tracing.valid_trace_id 와 동일 — path-traversal 차단
_TRACE_KIND_RE = re.compile(r"^[a-z0-9_]{1,32}$")
_TARGET_KIND = ("dm", "channel")


def _require(value: str, pattern: re.Pattern[str], *, name: str) -> str:
    if not isinstance(value, str) or not pattern.match(value):
        print(f"[remote] invalid {name}: {value!r}", file=sys.stderr)
        sys.exit(4)
    return value


def _require_slugs_csv(csv: str) -> str:
    """`s1,s2,s3` 형식 — 각 slug 가 _SLUG_RE 통과해야 함."""
    parts = [s for s in csv.split(",") if s]
    if not parts:
        print(f"[remote] empty slug list: {csv!r}", file=sys.stderr)
        sys.exit(4)
    for s in parts:
        _require(s, _SLUG_RE, name="slug")
    return ",".join(parts)


def _require_kind(kind: str) -> str:
    if kind not in _TARGET_KIND:
        print(f"[remote] invalid target_kind: {kind!r}. 허용: {_TARGET_KIND}", file=sys.stderr)
        sys.exit(4)
    return kind


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


_TRACE_ENV_KEYS = ("TRACE_ENABLED", "TRACE_ID", "TRACE_KIND", "TRACE_PARENT_SPAN")
_TRACE_ENV_VAL_RE = re.compile(r"^[A-Za-z0-9_\-]{0,64}$")  # injection 방지 — 값에도 영숫자만.


def _trace_env_prefix() -> str:
    """dev박스의 TRACE_* env 를 SSH command line 안 `export` 로 변환.

    inline `KEY=VAL cmd1 && cmd2` 는 cmd2 까지 안 닿음 (chain 안의 새 process). 그래서
    `export KEY=VAL; ...` 형태로 prepend 해 chain 전체에 적용. 값은 `_TRACE_ENV_VAL_RE`
    통과 해야만 — 임의 문자 (`;rm -rf ~`) injection 차단.
    """
    parts: list[str] = []
    for k in _TRACE_ENV_KEYS:
        v = os.environ.get(k, "")
        if not v:
            continue
        if not _TRACE_ENV_VAL_RE.match(v):
            continue
        parts.append(f"export {k}={v};")
    return (" ".join(parts) + " ") if parts else ""


def _ssh(remote_cmd: str) -> int:
    full = _trace_env_prefix() + remote_cmd
    p = subprocess.run(["ssh", DEPLOY_HOST, full], capture_output=True, text=True, errors="replace")
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
    # `--user -u <unit>` 는 systemd 일부 버전에서 user-scope journal 을 못 찾고 "No journal files were found"
    # 반환 (관찰: N100 Arch). `--user-unit <unit>` 또는 `_SYSTEMD_USER_UNIT=...` 로 명시해야 안정.
    return _ssh(f"journalctl --user-unit {u} -n {int(tail)} --no-pager")


def cmd_daemon_reload() -> int:
    return _ssh("systemctl --user daemon-reload")


def _remote_python_cmd(*args: str) -> str:
    """`cd $DEPLOY_PATH && .venv/bin/python <args>` 한 줄. args 는 *모두 사전 검증된* 토큰이어야 함.

    venv 의 python 을 명시 사용 — 시스템 python 엔 httpx/discord 등 의존성 없음. systemd 유닛은
    `ExecStart=.venv/bin/python …` 로 떠 있어 문제 없지만 ad-hoc SSH 호출은 `$PATH` 의 system
    python 으로 떨어져 ModuleNotFoundError 가 남.

    quote 안 함 — DEPLOY_PATH 는 모듈 로드 시점에 _DEPLOY_PATH_RE 로 검증되었고, 호출자가 넘긴
    args 는 _require*() 정규식을 통과한 토큰 (slug/snowflake/base64/`--flag` 형태)이라 shell
    metachar 가 없다. 임의 사용자 입력을 quote 없이 넘기는 일은 없어야 함.
    """
    return f"cd {DEPLOY_PATH_RAW} && .venv/bin/python " + " ".join(args)


def cmd_poll_now_slug(slugs_csv: str) -> int:
    csv = _require_slugs_csv(slugs_csv)
    return _ssh(_remote_python_cmd("scripts/poll.py", "--sites", csv))


def cmd_replay_deliveries(slug: str, target_kind: str, target_id: str,
                          post_id: Optional[str]) -> int:
    _require(slug, _SLUG_RE, name="slug")
    _require_kind(target_kind)
    _require(target_id, _TARGET_ID_RE, name="target_id")
    args = ["scripts/replay.py",
            "--slug", slug,
            "--target-kind", target_kind,
            "--target-id", target_id]
    if post_id:
        _require(post_id, _POST_ID_RE, name="post_id")
        args += ["--post-id", post_id]
    return _ssh(_remote_python_cmd(*args))


def cmd_notify_target(slug: str, target_kind: str, target_id: str) -> int:
    _require(slug, _SLUG_RE, name="slug")
    _require_kind(target_kind)
    _require(target_id, _TARGET_ID_RE, name="target_id")
    # notify.py 가 collected dir 의 *.new.json 중 그 slug 의 글을 그 target 에게만 발송.
    # poll-now 를 별도로 부르고 싶으면 replay-deliveries / poll-now-slug 를 먼저.
    return _ssh(_remote_python_cmd(
        "scripts/notify.py",
        "--only-target-kind", target_kind,
        "--only-target-id", target_id,
        "--no-digest",
    ))


def cmd_trace_index(kind: str) -> int:
    """`output/traces/index.<kind>.jsonl` cat. kind allowlist 강제."""
    _require(kind, _TRACE_KIND_RE, name="trace-kind")
    # tail 으로 마지막 N 줄만 — index 가 커져도 cat 부담 X.
    return _ssh(
        f"tail -n 5000 {DEPLOY_PATH_RAW}/output/traces/index.{kind}.jsonl 2>/dev/null || true"
    )


def cmd_trace_index_all() -> int:
    """모든 kind 의 index 를 합쳐 cat. 작은 박스라 cat 부담 X."""
    return _ssh(
        f"for f in {DEPLOY_PATH_RAW}/output/traces/index.*.jsonl; do "
        f"[ -f \"$f\" ] && tail -n 5000 \"$f\"; done"
    )


def cmd_trace_fetch(trace_id: str) -> int:
    """단일 trace 의 JSONL cat — path-traversal 차단을 위해 trace_id allowlist."""
    _require(trace_id, _TRACE_ID_RE, name="trace-id")
    return _ssh(f"cat {DEPLOY_PATH_RAW}/output/traces/{trace_id}.jsonl")


def cmd_announce_scoped(b64: str) -> int:
    """base64-인코딩된 JSON 페이로드를 받아 N100 의 `scripts/announce.py --base64` 로 전달.

    페이로드 검증은 announce.py 가 함 (title/message 길이, recipients 형식 등). 여기선
    base64 문자셋만 검증 → SSH 명령 안전 interpolation 보장.
    """
    _require(b64, _BASE64_RE, name="base64-payload")
    return _ssh(_remote_python_cmd("scripts/announce.py", "--base64", b64))


def cmd_read(alias: str) -> int:
    if alias not in READABLE:
        print(f"[remote] 알 수 없는 read alias: {alias!r}. 허용: {sorted(READABLE)}", file=sys.stderr)
        return 4
    path = READABLE[alias]
    # `cat` 만 — 쓰기/실행 권한 X. path 는 우리가 만든 READABLE 매핑 + 모듈 로드 시 검증한 DEPLOY_PATH 만 사용 →
    # shell metachar 안전. quote 안 함 (single-quote 는 `~/` 의 tilde 확장을 깨뜨림).
    return _ssh(f"cat {path}")


def list_actions() -> int:
    print("commands:")
    print("  poll-now                                       notice-poll.service 즉시 실행")
    print("  restart-bot                                    notice-bot.service 재시작")
    print("  status [unit]                                  systemctl --user status (default: bot)")
    print("  logs <unit> [--tail N]                         journalctl --user -u")
    print("  daemon-reload                                  systemctl --user daemon-reload")
    print("  read <alias>                                   원격 파일 cat (allowlist)")
    print("  poll-now-slug <s1,s2,...>                      부분 poll-now (slug 일부)")
    print("  replay-deliveries <slug> <kind> <id> [post]    M2/M3 replay (lock+직렬)")
    print("  notify-target <slug> <kind> <id>               collected → 그 target 만 발송")
    print("  announce-scoped <base64-json>                  좁힌 공지 발송")
    print("  trace-index <kind>                             output/traces/index.<kind>.jsonl tail")
    print("  trace-index-all                                모든 kind index 합본")
    print("  trace-fetch <trace_id>                         output/traces/<trace_id>.jsonl cat")
    print()
    print(f"unit aliases: {', '.join(sorted(UNITS))}")
    print(f"read aliases: {', '.join(sorted(READABLE))}")
    print(f"target kinds: {', '.join(_TARGET_KIND)}")
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
    sp = sub.add_parser("poll-now-slug"); sp.add_argument("slugs", help="콤마 구분 slug 리스트")
    sp = sub.add_parser("replay-deliveries")
    sp.add_argument("slug"); sp.add_argument("target_kind"); sp.add_argument("target_id")
    sp.add_argument("post_id", nargs="?", default=None)
    sp = sub.add_parser("notify-target")
    sp.add_argument("slug"); sp.add_argument("target_kind"); sp.add_argument("target_id")
    sp = sub.add_parser("announce-scoped"); sp.add_argument("base64_payload")
    sp = sub.add_parser("trace-index"); sp.add_argument("kind", help="poll|notify|notify_idle|probe ...")
    sub.add_parser("trace-index-all")
    sp = sub.add_parser("trace-fetch"); sp.add_argument("trace_id")
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
    if args.cmd == "poll-now-slug":
        return cmd_poll_now_slug(args.slugs)
    if args.cmd == "replay-deliveries":
        return cmd_replay_deliveries(args.slug, args.target_kind, args.target_id, args.post_id)
    if args.cmd == "notify-target":
        return cmd_notify_target(args.slug, args.target_kind, args.target_id)
    if args.cmd == "announce-scoped":
        return cmd_announce_scoped(args.base64_payload)
    if args.cmd == "trace-index":
        return cmd_trace_index(args.kind)
    if args.cmd == "trace-index-all":
        return cmd_trace_index_all()
    if args.cmd == "trace-fetch":
        return cmd_trace_fetch(args.trace_id)
    print(f"[remote] unknown cmd {args.cmd!r}", file=sys.stderr)
    return 4


if __name__ == "__main__":
    sys.exit(main())
