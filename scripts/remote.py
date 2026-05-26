"""운영 호스트 원격 명령 실행 CLI. allowlist 강제 — 임의 명령 X.

사용:
    python scripts/remote.py poll-now                                       # 폴링 즉시 1회 실행
    python scripts/remote.py restart-bot                                    # Discord 봇 재시작
    python scripts/remote.py status [unit]                                  # systemctl status
    python scripts/remote.py logs bot --tail 200                            # journalctl
    python scripts/remote.py logs poll --tail 100
    python scripts/remote.py daemon-reload                                  # 유닛 변경 후
    python scripts/remote.py read routing                                   # 원격 파일 cat (allowlist)
    python scripts/remote.py poll-now-slug s1,s2                            # 부분 poll-now + notify (정상 pipeline; fan-out)
    python scripts/remote.py poll-now-slug-quiet s1,s2                      # poll 만 (notify X; m1_solo 격리 발송용)
    python scripts/remote.py replay-deliveries <slug> <kind> <id> [post]    # M2/M3 replay (lock 잡고 직렬)
    python scripts/remote.py notify-target <slug> <kind> <id>               # collected → 그 target 만 발송
    python scripts/remote.py announce-scoped <base64-json>                  # 좁힌 공지 발송
    python scripts/remote.py batch-register --catalog <name> [...]          # catalog 1개+ 의 untried enqueue
    python scripts/remote.py batch-register --url URL [--url URL ...]       # 명시 URL 만 retry
    python scripts/remote.py batch-register --catalog <name> --failed       # gen_fail+bug retry
    python scripts/remote.py batch-register --catalog <name> --rc 1,-99     # 특정 rc retry
    python scripts/remote.py batch-register --catalog <name> --force        # catalog 전체 retry
    python scripts/remote.py jobs [--kind register] [--since 60] [--min-id N]
                                                                            # bot.sqlite3 jobs 상태 카운트 (SSH+sqlite3 인용 직접 작성 X)
    python scripts/remote.py list                                           # 허용 명령 출력

dashboard 가 subprocess 로 호출. stdout 그대로 캡처해 토스트/박스에 표시.

설계:
- 명령은 ACTIONS dict 의 enum (SSH command injection 차단). 사용자 인자는 정해진 알리아스만 매핑.
- 자유 입력(slug, target_id, post_id, base64 payload) 은 정규식으로 거른 뒤에만 SSH command 에 interpolation.
- 모든 verb 의 운영 호스트 측 실행 = `cd $DEPLOY_PATH && python scripts/<helper>.py …` — 인자는 항상 끝에 append, base64 같은 큰 페이로드도 shell escape 안전 (base64 문자셋 [A-Za-z0-9+/=] 는 metachar 없음).
- DEPLOY_HOST 는 env 로만 받음 (인자로 호스트 받으면 위험).
- 결과 코드: SSH 종료 코드 그대로 전파 (0=성공). stdout 만 print.
"""
from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
import time
from typing import Optional


DEPLOY_HOST = os.environ.get("DEPLOY_HOST", "")
DEPLOY_PATH_RAW = os.environ.get("DEPLOY_PATH", "~/notice-watcher")

# DEPLOY_PATH 가 SSH command 에 직접 interpolation 되므로 안전 문자만 허용. 위반 시 즉시 거부.
# 허용: 영숫자, `_`, `.`, `/`, `-`, `~`, `$` (예: `~/notice-watcher`, `$HOME/foo`).
_DEPLOY_PATH_RE = re.compile(r"^[A-Za-z0-9_./~$-]+$")
if not _DEPLOY_PATH_RE.match(DEPLOY_PATH_RAW):
    raise SystemExit(f"[remote] DEPLOY_PATH unsafe characters: {DEPLOY_PATH_RAW!r}")


def _require_deploy_host() -> str:
    if DEPLOY_HOST:
        return DEPLOY_HOST
    raise RuntimeError(
        "DEPLOY_HOST 환경변수가 설정되지 않았습니다. 운영 호스트 SSH 대상을 지정하세요 "
        "(예: PowerShell `$env:DEPLOY_HOST = 'user@host'`, bash `export DEPLOY_HOST=user@host`)."
    )

# 자유 입력 인자 validation — interpolation 전 거름.
_SLUG_RE = re.compile(r"^[A-Za-z0-9._%\-]{1,200}$")           # engine.slug 형식 — `%` 포함(URL-encoded UTF-8 seg)
_TARGET_ID_RE = re.compile(r"^[0-9]{1,32}$")                    # Discord snowflake (현재 19자리, 미래 여유)
_POST_ID_RE = re.compile(r"^[\w\-./:%]{1,128}$")               # poll.py 의 _STABLE_ID_RE 와 동일
_BASE64_RE = re.compile(r"^[A-Za-z0-9+/=]{1,200000}$")         # base64 문자셋만; ≤200KB 페이로드
_TRACE_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")          # tracing.valid_trace_id 와 동일 — path-traversal 차단
_TRACE_KIND_RE = re.compile(r"^[a-z0-9_]{1,32}$")
_PATTERN_ID_RE = re.compile(r"^[a-f0-9]{1,12}$")              # learned_blacklist pattern id (sha1 12자)
_JOB_KIND_RE = re.compile(r"^[a-z_]{1,32}$")                  # bot.sqlite3 jobs.kind 컬럼 — 영소문자+_
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
    "learned":  f"{DEPLOY_PATH_RAW}/output/learned_blacklist.json",
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
    p = subprocess.run(["ssh", _require_deploy_host(), full], capture_output=True, text=True, errors="replace")
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
    # 반환 (관찰: 일부 systemd 환경). `--user-unit <unit>` 또는 `_SYSTEMD_USER_UNIT=...` 로 명시해야 안정.
    return _ssh(f"journalctl --user-unit {u} -n {int(tail)} --no-pager")


def cmd_daemon_reload() -> int:
    return _ssh("systemctl --user daemon-reload")


def _remote_python_cmd(*args: str) -> str:
    """`cd $DEPLOY_PATH && .venv/bin/python <args>` 한 줄.

    venv 의 python 을 명시 사용 — 시스템 python 엔 httpx/discord 등 의존성 없음. systemd 유닛은
    `ExecStart=.venv/bin/python …` 로 떠 있어 문제 없지만 ad-hoc SSH 호출은 `$PATH` 의 system
    python 으로 떨어져 ModuleNotFoundError 가 남.

    args 는 `shlex.quote` 로 shell-escape — 호출자 regex 가 차단 못한 metachar (예: `_URL_ARG_RE`
    가 허용하는 `;` `$` `&` `(` `)`) 가 흘러도 안전. DEPLOY_PATH 는 unquoted (tilde 확장 필요).
    """
    quoted_args = " ".join(shlex.quote(a) for a in args)
    return f"cd {DEPLOY_PATH_RAW} && .venv/bin/python {quoted_args}"


def cmd_poll_now_slug(slugs_csv: str) -> int:
    """정상 pipeline — poll_cron.py 가 poll.py 띄움 (chromium 사이트별 per-site lock, ADR 0019 Phase 1).
    발송은 분리 (ADR 0006) — 봇 1분 tick + deliver_due.py 가 사용자 발송시각에 처리.

    이 명령은 폴링 즉시 1회. 새 글은 posts 캐시에 박힘 + collected/*.new.json. 발송은 별도 tick.
    """
    csv = _require_slugs_csv(slugs_csv)
    return _ssh(_remote_python_cmd("scripts/poll_cron.py", "--sites", csv))


def cmd_poll_now_slug_quiet(slugs_csv: str) -> int:
    """poll.py 만 — notify 단계 생략. m1_solo 가 직후 notify-target 으로 격리 발송하기 위함."""
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
    # `--heartbeat` 켜는 이유: 새 글 0건이고 그 target 의 구독이 notify_empty=1 이면 "새 공지 없음"
    # 한 줄도 발송. m1_solo 액션이 침묵 안 하게 (dashboard UX).
    # poll-now 를 별도로 부르고 싶으면 replay-deliveries / poll-now-slug 를 먼저.
    return _ssh(_remote_python_cmd(
        "scripts/notify.py",
        "--only-target-kind", target_kind,
        "--only-target-id", target_id,
        "--no-digest",
        "--heartbeat",
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


def cmd_unlearn(pattern_id: str) -> int:
    """learned_blacklist 의 pattern entry 제거 (false positive 손-회수).
    운영 호스트의 `scripts/register.py --unlearn <id>` 호출 — atomic write 보장 + shell-quoting 안전.
    pattern_id 는 [a-f0-9]{1,12} 만 (path-traversal/injection 차단)."""
    pid = _require(pattern_id, _PATTERN_ID_RE, name="pattern_id")
    return _ssh(_remote_python_cmd("scripts/register.py", "--unlearn", pid))


_SLUG_RE = re.compile(r"^[A-Za-z0-9._%-]+$")


def cmd_clear_bug(slug: str) -> int:
    """`.BUG.json` 마커 제거 — bug-fix workflow 마지막 step (대시보드 Clear 버튼).

    운영 호스트의 `scripts/register.py --clear-bug <slug>` 호출 + dev box 의
    `output/snapshot/poll_state/<slug>.BUG.json` 도 즉시 제거 (dashboard `/bugs` 가
    snapshot 읽음 — N100 만 정리하면 stale 표시). 2026-05-24 박힘 — podcast batch 에서
    bot 측 BUG 해제 후 dashboard 가 1 잔여 표시 (snapshot stale).
    """
    s = _require(slug, _SLUG_RE, name="slug")
    rc = _ssh(_remote_python_cmd("scripts/register.py", "--clear-bug", s))
    if rc == 0:
        snap = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "output", "snapshot", "poll_state", f"{s}.BUG.json",
        )
        try:
            if os.path.exists(snap):
                os.remove(snap)
                print(f"[remote] dev snapshot BUG marker 도 제거: {snap}")
        except OSError as e:
            print(f"[remote] ⚠ dev snapshot BUG marker 제거 실패: {e}", file=sys.stderr)
    return rc


_URL_ARG_RE = re.compile(r"^https?://[A-Za-z0-9._~\-]+(?::\d+)?/[A-Za-z0-9._~%:/?#\[\]@!$&'()*+,;=\-]*$")
_CATALOG_NAME_ARG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_RC_LIST_ARG_RE = re.compile(r"^-?\d+(?:,-?\d+)*$")

# rev6: dev box 의 output/candidates/ 가 catalog 단일 진본. 운영 호스트는 batch-register 시 atomic
# scp 로 동기. configs/candidates/ 는 폐기 (예전 git-tracked 위치).
_LOCAL_CATALOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "output", "candidates",
)


def _sync_catalogs_to_n100(catalogs: list[str]) -> int:
    """각 catalog yaml 을 dev box → 운영 호스트 atomic scp.

    절차 (per catalog):
      1. dev box 의 `output/candidates/<name>.yaml` 존재 확인 — 없으면 abort.
      2. SSH `mkdir -p $HOME/notice-watcher/output/candidates/` (idempotent).
      3. scp local → 운영 호스트의 `output/candidates/.tmp.<name>.<pid>.yaml`.
      4. SSH `mv` → `output/candidates/<name>.yaml` (atomic rename).
      5. 실패 시 운영 호스트의 temp 정리 시도 + return 0 아닌 값.

    quoting: DEPLOY_PATH_RAW + name 둘 다 module-load 시점 regex 검증 (`_DEPLOY_PATH_RE`,
    `_CATALOG_NAME_ARG_RE`) — shell metachar 없음. tilde 확장 보존 위해 unquoted.

    rc:
      0  모든 catalog 동기 성공
      5  로컬 yaml 없음
      6  scp / SSH 실패
    """
    deploy_host = _require_deploy_host()
    pid = os.getpid()
    for name in catalogs:
        if not _CATALOG_NAME_ARG_RE.match(name):
            print(f"[remote] invalid catalog name: {name!r}", file=sys.stderr)
            return 4
        local = os.path.join(_LOCAL_CATALOG_DIR, f"{name}.yaml")
        if not os.path.isfile(local):
            print(f"[remote] catalog yaml 없음: {local}", file=sys.stderr)
            return 5
        # DEPLOY_PATH_RAW 의 tilde 확장 보존 — unquoted. name·pid 도 regex 검증된 안전 토큰.
        remote_dir = f"{DEPLOY_PATH_RAW}/output/candidates"
        remote_final = f"{remote_dir}/{name}.yaml"
        remote_tmp = f"{remote_dir}/.tmp.{name}.{pid}.yaml"
        # 1. mkdir (idempotent)
        rc = subprocess.run(
            ["ssh", deploy_host, f"mkdir -p {remote_dir}"],
            capture_output=True, text=True,
        )
        if rc.returncode != 0:
            print(f"[remote] 운영 호스트 mkdir 실패: {rc.stderr}", file=sys.stderr)
            return 6
        # 2. scp → temp. scp 의 remote dest 는 unquoted — tilde 확장 위함 (sshd 측 shell 처리).
        rc = subprocess.run(
            ["scp", "-q", local, f"{deploy_host}:{remote_tmp}"],
            capture_output=True, text=True,
        )
        if rc.returncode != 0:
            print(f"[remote] scp 실패 ({name}): {rc.stderr or rc.stdout}", file=sys.stderr)
            # temp 청소 시도 (best-effort)
            subprocess.run(
                ["ssh", deploy_host, f"rm -f {remote_tmp}"],
                capture_output=True, text=True,
            )
            return 6
        # 3. atomic rename
        rc = subprocess.run(
            ["ssh", deploy_host, f"mv {remote_tmp} {remote_final}"],
            capture_output=True, text=True,
        )
        if rc.returncode != 0:
            print(f"[remote] 운영 호스트 mv 실패 ({name}): {rc.stderr}", file=sys.stderr)
            # 실패한 temp 청소
            subprocess.run(
                ["ssh", deploy_host, f"rm -f {remote_tmp}"],
                capture_output=True, text=True,
            )
            return 6
        print(f"[remote] catalog 동기: {name}.yaml → 운영 호스트")
    return 0


def cmd_batch_register(
    catalogs: list[str],
    urls: list[str],
    failed: bool,
    rc: str,
    force: bool,
) -> int:
    """운영 호스트의 `scripts/register_batch.py` 호출 — catalog/url scope × filter (untried/failed/rc/force).

    rev6 변경: catalog scope 면 *호출 전* dev box 의 `output/candidates/<name>.yaml` 을 운영 호스트로
    atomic scp 동기. 즉 dashboard live edit 이 git 안 거치고 즉시 다음 batch run 에 반영됨.
    scp 실패 시 hard abort — stale yaml 로 register 진행 X.

    - scope: `--catalog` 이름 / `--url` 직접 URL 중 하나 이상.
    - filter: default(untried) / `--failed` (rc∈{1,-1,-2,-3,-99}) / `--rc=<list>` / `--force` (모두 override).
    - 인자 검증: 모두 regex 통과해야 SSH command interpolation. metachar injection 차단.
    """
    if not catalogs and not urls:
        print("[remote] --catalog 또는 --url 중 하나 이상 필요", file=sys.stderr)
        return 4
    if failed and rc:
        print("[remote] --failed 와 --rc 동시 사용 불가", file=sys.stderr)
        return 4
    # catalog 인자 검증 + dev → 운영 호스트 동기 (scp 실패 시 abort).
    if catalogs:
        sync_rc = _sync_catalogs_to_n100(catalogs)
        if sync_rc != 0:
            return sync_rc
    args = ["scripts/register_batch.py"]
    for c in catalogs:
        # _sync_catalogs_to_n100 가 이미 검증 — 중복이지만 보수적.
        if not _CATALOG_NAME_ARG_RE.match(c):
            print(f"[remote] invalid catalog name: {c!r}", file=sys.stderr)
            return 4
        args += ["--catalog", c]
    for u in urls:
        if not _URL_ARG_RE.match(u):
            print(f"[remote] invalid url: {u!r}", file=sys.stderr)
            return 4
        args += ["--url", u]
    if failed:
        args.append("--failed")
    if rc:
        if not _RC_LIST_ARG_RE.match(rc):
            print(f"[remote] invalid rc list (정수,콤마 만): {rc!r}", file=sys.stderr)
            return 4
        args += ["--rc", rc]
    if force:
        args.append("--force")
    return _ssh(_remote_python_cmd(*args))


def cmd_announce_scoped(b64: str) -> int:
    """base64-인코딩된 JSON 페이로드를 받아 운영 호스트의 `scripts/announce.py --base64` 로 전달.

    페이로드 검증은 announce.py 가 함 (title/message 길이, recipients 형식 등). 여기선
    base64 문자셋만 검증 → SSH 명령 안전 interpolation 보장.
    """
    _require(b64, _BASE64_RE, name="base64-payload")
    return _ssh(_remote_python_cmd("scripts/announce.py", "--base64", b64))


_IN_FLIGHT_STATUSES = ("pending", "running")


def _jobs_status_bucket_expr() -> str:
    """SQL expression for the status buckets shown by `remote.py jobs`.

    rc=5 is `capability_blocked`: operationally failed, but not a gen_fail work item.
    Show it separately so batch drain output does not merge blocked sites into failed.
    """
    return (
        "CASE "
        "WHEN status='failed' AND result_rc=5 THEN 'blocked' "
        "WHEN status='failed' THEN 'failed' "
        "ELSE status END"
    )


def _jobs_query(kind: str, since_minutes: int, min_id: int) -> tuple[int, str, str, dict[str, int], int]:
    """jobs 테이블 1회 조회. returns (rc, stdout_human, stderr, status_counts, total).

    stdout_human = column-formatted (사용자 view). status_counts = parsed dict.
    total = `total` row 의 count (있으면, 없으면 sum).
    """
    where = f"kind='{kind}' AND created_at > datetime('now', '-{int(since_minutes)} minutes')"
    if min_id > 0:
        where += f" AND id >= {int(min_id)}"
    # 두 SQL 한 ssh 호출에 묶음 — 사람 view (column) + 파싱 view (pipe-list).
    bucket = _jobs_status_bucket_expr()
    sql = (
        f".headers on\n.mode column\n"
        f"SELECT {bucket} AS status, COUNT(*) AS n FROM jobs WHERE {where} GROUP BY 1 ORDER BY 1;\n"
        f"SELECT 'total' AS status, COUNT(*) AS n FROM jobs WHERE {where};\n"
        f".headers off\n.mode list\n.separator '|'\n"
        f"SELECT '__parse__';\n"
        f"SELECT {bucket}, COUNT(*) FROM jobs WHERE {where} GROUP BY 1;\n"
        f"SELECT '__total__', COUNT(*) FROM jobs WHERE {where};\n"
    )
    remote = f"cd {DEPLOY_PATH_RAW} && sqlite3 output/bot.sqlite3"
    p = subprocess.run(
        ["ssh", _require_deploy_host(), remote],
        input=sql,
        capture_output=True,
        text=True,
        errors="replace",
    )
    counts: dict[str, int] = {}
    total = 0
    human = p.stdout or ""
    if "__parse__" in human:
        human, _, tail = human.partition("__parse__")
        human = human.rstrip() + "\n"
        for line in tail.splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            k, _, v = line.partition("|")
            try:
                n = int(v.strip())
            except ValueError:
                continue
            if k == "__total__":
                total = n
            else:
                counts[k.strip()] = n
    return p.returncode, human, (p.stderr or ""), counts, total


def cmd_jobs(kind: str, since_minutes: int, min_id: int, *,
             wait: bool = False, interval: int = 60, max_wait: int = 3600) -> int:
    """운영 호스트 `output/bot.sqlite3` jobs 테이블의 상태별 카운트.

    batch drain 모니터링용. ad-hoc `ssh ... 'sqlite3 ... "SELECT ... WHERE kind=\"register\""'`
    형태로 직접 쓰면 SSH/PowerShell/Bash/SQL 4중 인용이 꼬여 SQL 이 `"register"` 를
    *identifier(컬럼명)* 로 해석하는 사고가 잘 난다 (2026-05-24 박음). 이 helper 가
    SQL 문자열 인용(=single-quote)·shell 인용을 한 자리에 박는다 — 호출자는 인용 X.

    `--wait` 모드: pending+running=0 될 때까지 polling, exit 0. 2026-05-25 박음
    — 이전 인라인 regex 패턴(`(pending|running)\\s+(\\d+)` findall) 은 drain
    완료 시 0행 row 가 출력에서 사라지면 매칭 0건 → `bool([])=False` → 무한 loop 버그.
    이 helper 는 SQL count 직접 본다(0행도 0 으로 알림).

    인자는 모두 regex/int 로 검증 → SSH command 안전 interpolation. SQL 안의 값은
    int(고정 변환)·whitelisted kind 만 들어가므로 injection 표면 0.
    """
    _require(kind, _JOB_KIND_RE, name="kind")
    if since_minutes < 0 or since_minutes > 60 * 24 * 30:
        print(f"[remote] since 범위 0..43200 분 (30일): {since_minutes!r}", file=sys.stderr)
        return 4
    if min_id < 0 or min_id > 10_000_000:
        print(f"[remote] min-id 범위 0..10000000: {min_id!r}", file=sys.stderr)
        return 4
    if wait:
        if interval < 5 or interval > 600:
            print(f"[remote] --interval 범위 5..600 초: {interval!r}", file=sys.stderr)
            return 4
        if max_wait < interval or max_wait > 60 * 60 * 24:
            print(f"[remote] --max-wait 범위 {interval}..86400 초: {max_wait!r}", file=sys.stderr)
            return 4
        elapsed = 0
        while True:
            rc, human, stderr, counts, total = _jobs_query(kind, since_minutes, min_id)
            if rc != 0:
                sys.stdout.write(human)
                sys.stderr.write(stderr)
                print(f"[remote] jobs query failed rc={rc}; abort wait", file=sys.stderr)
                return rc
            sys.stdout.write(human)
            in_flight = sum(counts.get(s, 0) for s in _IN_FLIGHT_STATUSES)
            sys.stdout.write(f"[remote] elapsed={elapsed}s in_flight={in_flight} total={total}\n---\n")
            sys.stdout.flush()
            if in_flight == 0 and total > 0:
                print("DRAIN COMPLETE", flush=True)
                return 0
            if elapsed >= max_wait:
                print(f"[remote] --max-wait {max_wait}s 도달, 여전히 in_flight={in_flight}", file=sys.stderr)
                return 2
            time.sleep(interval)
            elapsed += interval
    rc, human, stderr, _counts, _total = _jobs_query(kind, since_minutes, min_id)
    sys.stdout.write(human)
    sys.stderr.write(stderr)
    return rc


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
    print("  poll-now-slug <s1,s2,...>                      부분 poll-now + notify (정상 pipeline; fan-out)")
    print("  poll-now-slug-quiet <s1,s2,...>                poll 만 (notify X; m1_solo 격리 발송용)")
    print("  replay-deliveries <slug> <kind> <id> [post]    M2/M3 replay (lock+직렬)")
    print("  notify-target <slug> <kind> <id>               collected → 그 target 만 발송")
    print("  announce-scoped <base64-json>                  좁힌 공지 발송")
    print("  batch-register --catalog <name>[...] [--url URL ...] [--failed|--rc 1,-99|--force]")
    print("                                                 catalog/url scope × filter (rev5)")
    print("  jobs [--kind register] [--since 60] [--min-id N]")
    print("                                                 bot.sqlite3 jobs 상태 카운트 (drain 모니터링)")
    print("  unlearn <pattern_id>                           learned_blacklist 패턴 제거")
    print("  clear-bug <slug>                               .BUG.json 마커 제거 (bug-fix workflow)")
    print("  trace-index <kind>                             output/traces/index.<kind>.jsonl tail")
    print("  trace-index-all                                모든 kind index 합본")
    print("  trace-fetch <trace_id>                         output/traces/<trace_id>.jsonl cat")
    print()
    print(f"unit aliases: {', '.join(sorted(UNITS))}")
    print(f"read aliases: {', '.join(sorted(READABLE))}")
    print(f"target kinds: {', '.join(_TARGET_KIND)}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="운영 호스트 원격 명령 (allowlist)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("poll-now")
    sub.add_parser("restart-bot")
    sp = sub.add_parser("status"); sp.add_argument("unit", nargs="?", default="bot")
    sp = sub.add_parser("logs"); sp.add_argument("unit"); sp.add_argument("--tail", type=int, default=100)
    sub.add_parser("daemon-reload")
    sp = sub.add_parser("read"); sp.add_argument("alias")
    sub.add_parser("list")
    sp = sub.add_parser("poll-now-slug"); sp.add_argument("slugs", help="콤마 구분 slug 리스트")
    sp = sub.add_parser("poll-now-slug-quiet"); sp.add_argument("slugs", help="콤마 구분 slug 리스트 (notify 생략)")
    sp = sub.add_parser("replay-deliveries")
    sp.add_argument("slug"); sp.add_argument("target_kind"); sp.add_argument("target_id")
    sp.add_argument("post_id", nargs="?", default=None)
    sp = sub.add_parser("notify-target")
    sp.add_argument("slug"); sp.add_argument("target_kind"); sp.add_argument("target_id")
    sp = sub.add_parser("announce-scoped"); sp.add_argument("base64_payload")
    sp = sub.add_parser("batch-register")
    sp.add_argument("--catalog", action="append", default=[],
                    help="catalog 이름 (파일명 stem). 반복 가능. e.g. --catalog 2026-05-20")
    sp.add_argument("--url", action="append", default=[],
                    help="명시한 URL 만 retry (반복 가능)")
    sp.add_argument("--failed", action="store_true",
                    help="rc∈{1,-1,-2,-3,-99} URL retry (마커 자동 clear)")
    sp.add_argument("--rc", default="",
                    help="rc filter (comma-list). e.g. --rc 1,-99")
    sp.add_argument("--force", action="store_true",
                    help="jobs / marker 다 무시 (filter override)")
    sp = sub.add_parser("jobs", help="bot.sqlite3 jobs 상태 카운트 (drain 모니터링; SSH+sqlite3 인용 wrap)")
    sp.add_argument("--kind", default="register", help="jobs.kind 컬럼 (영소문자+_, default: register)")
    sp.add_argument("--since", type=int, default=60, help="최근 N분 (default: 60)")
    sp.add_argument("--min-id", type=int, default=0, dest="min_id", help="id >= N filter (batch 시작 id 부터 보고 싶을 때)")
    sp.add_argument("--wait", action="store_true",
                    help="drain 완료(pending+running=0)까지 polling, exit 0. 인라인 regex 패턴 대체 (drain 시 0행 표시→regex 0매칭→무한loop 버그 회피).")
    sp.add_argument("--interval", type=int, default=60,
                    help="--wait polling 간격(s, default: 60)")
    sp.add_argument("--max-wait", type=int, default=3600, dest="max_wait",
                    help="--wait 최대 대기(s, default: 3600). 초과 시 exit 2.")
    sp = sub.add_parser("unlearn"); sp.add_argument("pattern_id", help="learned_blacklist pattern id ([a-f0-9]{1,12})")
    sp = sub.add_parser("clear-bug"); sp.add_argument("slug", help="`.BUG.json` 마커가 박힌 slug")
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
    if args.cmd == "poll-now-slug-quiet":
        return cmd_poll_now_slug_quiet(args.slugs)
    if args.cmd == "replay-deliveries":
        return cmd_replay_deliveries(args.slug, args.target_kind, args.target_id, args.post_id)
    if args.cmd == "notify-target":
        return cmd_notify_target(args.slug, args.target_kind, args.target_id)
    if args.cmd == "announce-scoped":
        return cmd_announce_scoped(args.base64_payload)
    if args.cmd == "batch-register":
        return cmd_batch_register(args.catalog, args.url, args.failed, args.rc, args.force)
    if args.cmd == "jobs":
        return cmd_jobs(args.kind, args.since, args.min_id,
                        wait=args.wait, interval=args.interval, max_wait=args.max_wait)
    if args.cmd == "unlearn":
        return cmd_unlearn(args.pattern_id)
    if args.cmd == "clear-bug":
        return cmd_clear_bug(args.slug)
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
