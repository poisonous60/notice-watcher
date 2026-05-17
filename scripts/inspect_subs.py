"""inspect.py — 사용자 신고(`/report`) 와 등록된 구독을 dev박스에서 진단·열람.

`bot/admin.py` 의 `/admin` 명령들과 *같은* lib(`bot/inspector.py`)을 호출 — Discord 와 CLI 가 같은
데이터 모델·진단을 본다. 라이브 데이터는 N100 에만 있으므로 `pull` 로 snapshot 을 떨구고 그 다음
명령들은 snapshot 을 읽는다.

흐름:
  python scripts/inspect_subs.py pull                 # N100 → output/snapshot/{bot.sqlite3, poll_state/}, configs.snapshot/
  python scripts/inspect_subs.py reports              # 미해결 신고 목록 + (각 신고 자동 진단)
  python scripts/inspect_subs.py recent               # 최근 register 잡 20개 — 등록 흐름 추적
  python scripts/inspect_subs.py inspect report 12    # 신고 #12 풀 dump (jobs/subs/config/state/diagnose)
  python scripts/inspect_subs.py inspect job 87       # 잡 #87 풀 dump
  python scripts/inspect_subs.py inspect slug arca.live_b_X_category_Y  [--user <id>]
  python scripts/inspect_subs.py fetch <slug> [-n 5]  # 현 config 로 fetch_list 돌려 결과 출력 + 진단 갱신
  python scripts/inspect_subs.py diagnose <slug>      # fetch 없이 정적 진단만

N100 호스트: `DEPLOY_HOST` (기본 `<user>@<host>` — Tailscale MagicDNS), `DEPLOY_PATH` (기본 `~/notice-watcher`).
snapshot 디렉토리는 `.gitignore` 에 추가됨 — dev 의 git tracked `configs/` 는 절대 안 건드림.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot import db, inspector  # noqa: E402

SNAPSHOT_DIR = ROOT / "output" / "snapshot"
CONFIGS_SNAPSHOT = ROOT / "configs.snapshot"
DEPLOY_HOST = os.environ.get("DEPLOY_HOST", "<user>@<host>")
DEPLOY_PATH = os.environ.get("DEPLOY_PATH", "~/notice-watcher")


def _run(cmd: list[str], *, check: bool = False) -> tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    out = ((p.stdout or "") + (p.stderr or "")).strip()
    if check and p.returncode != 0:
        sys.stderr.write(f"[inspect] 명령 실패 ({p.returncode}): {' '.join(cmd)}\n{out}\n")
    return p.returncode, out


def _snapshot_paths() -> inspector.InspectorPaths:
    return inspector.InspectorPaths(
        db_path=SNAPSHOT_DIR / "bot.sqlite3",
        configs_dir=CONFIGS_SNAPSHOT,
        state_dir=SNAPSHOT_DIR / "poll_state",
    )


# --------------------------------------------------------------------------- #
# pull — N100 → 로컬 snapshot
# --------------------------------------------------------------------------- #
def cmd_pull() -> int:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    (SNAPSHOT_DIR / "poll_state").mkdir(parents=True, exist_ok=True)
    CONFIGS_SNAPSHOT.mkdir(parents=True, exist_ok=True)

    # 1) bot.sqlite3 — WAL 모드라 직접 scp 하면 최근 commit 누락 가능. N100 에서 .backup 으로 일관성 있는 사본 생성.
    remote_snap = "/tmp/inspect_snap.sqlite3"
    rc, out = _run([
        "ssh", DEPLOY_HOST,
        f"cd {DEPLOY_PATH} && sqlite3 output/bot.sqlite3 \".backup '{remote_snap}'\" && echo OK",
    ])
    if rc != 0 or "OK" not in out:
        sys.stderr.write(f"[inspect pull] sqlite .backup 실패: {out}\n")
        return 2
    rc, out = _run(["scp", "-q", f"{DEPLOY_HOST}:{remote_snap}", str(SNAPSHOT_DIR / "bot.sqlite3")])
    if rc != 0:
        sys.stderr.write(f"[inspect pull] DB scp 실패: {out}\n")
        return 2
    _run(["ssh", DEPLOY_HOST, f"rm -f {remote_snap}"])

    # 2) configs/ 통째 mirror — dev 의 configs/ 와 *분리된 폴더* (configs.snapshot/). N100 에서 삭제된 파일도
    #    snapshot 에서 사라지도록 매번 통째로 비우고 *.json 글로브로 개별 파일만 scp (triage.py 와 같은 패턴
    #    — `scp -r` dest-exists 중첩 동작이 OS 마다 다른 걸 회피). rc 비0 인데 "matches no files" 가
    #    아니면 진짜 실패 — stderr 로 알린다(원격 dir 자체가 없거나 권한 문제).
    import shutil
    if CONFIGS_SNAPSHOT.exists():
        shutil.rmtree(CONFIGS_SNAPSHOT)
    CONFIGS_SNAPSHOT.mkdir(parents=True)
    rc, out = _run(["scp", "-q", f"{DEPLOY_HOST}:{DEPLOY_PATH}/configs/*.json",
                    f"{CONFIGS_SNAPSHOT}{os.sep}"])
    if rc != 0 and not any(s in out for s in ("No such file", "matches no files", "not match")):
        sys.stderr.write(f"[inspect pull] configs scp 실패 (rc={rc}): {out}\n")

    # poll_state 도 같은 이유로 매번 비우고 받음 — N100 에서 삭제된 slug 가 stale 채로 남는 걸 막음.
    for old in (SNAPSHOT_DIR / "poll_state").glob("*"):
        try:
            old.unlink()
        except OSError:
            pass
    rc, out = _run(["scp", "-q", f"{DEPLOY_HOST}:{DEPLOY_PATH}/output/poll_state/*.json",
                    f"{SNAPSHOT_DIR}{os.sep}poll_state{os.sep}"])
    if rc != 0 and not any(s in out for s in ("No such file", "matches no files", "not match")):
        sys.stderr.write(f"[inspect pull] poll_state scp 실패 (rc={rc}): {out}\n")

    # 3) usage.sqlite3 — LLM 호출 기록. WAL 모드라 동일하게 .backup 으로 일관성 있는 사본 생성.
    #    실패해도 치명적이지 X — 파일 없음/접근 불가면 skip + 경고만.
    remote_usage_snap = "/tmp/inspect_usage_snap.sqlite3"
    rc, out = _run([
        "ssh", DEPLOY_HOST,
        f"cd {DEPLOY_PATH} && "
        f"if [ -f output/usage.sqlite3 ]; then "
        f"sqlite3 output/usage.sqlite3 \".backup '{remote_usage_snap}'\" && echo OK; "
        f"else echo SKIP_NO_FILE; fi",
    ])
    if rc == 0 and "OK" in out:
        rc2, out2 = _run(["scp", "-q", f"{DEPLOY_HOST}:{remote_usage_snap}", str(SNAPSHOT_DIR / "usage.sqlite3")])
        if rc2 != 0:
            sys.stderr.write(f"[inspect pull] usage.sqlite3 scp 실패: {out2}\n")
        _run(["ssh", DEPLOY_HOST, f"rm -f {remote_usage_snap}"])
    elif "SKIP_NO_FILE" in out:
        # 아직 LLM 호출 한 적 없음 — 정상
        pass
    else:
        sys.stderr.write(f"[inspect pull] usage.sqlite3 .backup 실패(skip): {out}\n")

    # 4) learned_blacklist.json — 자동 학습된 거부 패턴. 없으면 skip (봇 운영 중 아직 거부 한 건도 없으면 정상).
    learned_dst = SNAPSHOT_DIR / "learned_blacklist.json"
    if learned_dst.exists():
        try:
            learned_dst.unlink()
        except OSError:
            pass
    rc, out = _run(["scp", "-q", f"{DEPLOY_HOST}:{DEPLOY_PATH}/output/learned_blacklist.json",
                    str(learned_dst)])
    # 없으면 정상 — stderr 경고도 안 띄움.
    if rc != 0 and not any(s in out for s in ("No such file", "matches no files", "not match")):
        sys.stderr.write(f"[inspect pull] learned_blacklist scp 실패 (rc={rc}): {out}\n")

    # 요약
    n_db = (SNAPSHOT_DIR / "bot.sqlite3").stat().st_size if (SNAPSHOT_DIR / "bot.sqlite3").exists() else 0
    n_usage = (SNAPSHOT_DIR / "usage.sqlite3").stat().st_size if (SNAPSHOT_DIR / "usage.sqlite3").exists() else 0
    n_states = sum(1 for _ in (SNAPSHOT_DIR / "poll_state").glob("*.json"))
    n_cfgs = sum(1 for _ in CONFIGS_SNAPSHOT.glob("*.json"))
    n_learned = 0
    if learned_dst.exists():
        try:
            _ldata = json.loads(learned_dst.read_text(encoding="utf-8"))
            n_learned = len(_ldata.get("patterns") or [])
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            n_learned = 0
    print(f"[inspect pull] {DEPLOY_HOST}:{DEPLOY_PATH} → {SNAPSHOT_DIR} + {CONFIGS_SNAPSHOT}")
    print(f"  bot.sqlite3: {n_db:,} bytes   usage.sqlite3: {n_usage:,} bytes   "
          f"poll_state: {n_states}개   configs: {n_cfgs}개   learned: {n_learned}건")
    return 0


# --------------------------------------------------------------------------- #
# read 명령들
# --------------------------------------------------------------------------- #
def _open_snapshot_conn():
    paths = _snapshot_paths()
    if not paths.db_path.exists():
        sys.stderr.write(f"[inspect] snapshot DB 없음 ({paths.db_path}) — 먼저 `python scripts/inspect_subs.py pull`\n")
        return None, paths
    conn = db.connect(paths.db_path)
    return conn, paths


def cmd_recent(args) -> int:
    conn, _ = _open_snapshot_conn()
    if conn is None:
        return 2
    rows = inspector.recent_jobs(conn, limit=args.n)
    print(inspector.format_recent_jobs(rows))
    return 0


def cmd_reports(args) -> int:
    conn, paths = _open_snapshot_conn()
    if conn is None:
        return 2
    status = None if args.status == "all" else args.status
    rows = [dict(r) for r in db.list_reports(conn, status=status, limit=args.n)]
    print(inspector.format_reports(rows))
    if args.verbose:
        for r in rows:
            result = inspector.inspect(conn, paths, report_id=r["id"])
            if result is None:
                continue
            print("\n" + "-" * 60)
            print(inspector.format_inspect_result(result))
    return 0


def cmd_inspect(args) -> int:
    conn, paths = _open_snapshot_conn()
    if conn is None:
        return 2
    kw: dict = {}
    if args.kind == "report":
        kw["report_id"] = int(args.target)
    elif args.kind == "job":
        kw["job_id"] = int(args.target)
    elif args.kind == "slug":
        kw["slug"] = args.target
        if args.user:
            kw["user_id"] = args.user
    elif args.kind == "user":
        if not args.slug:
            sys.stderr.write("[inspect] user 모드는 --slug 필요\n")
            return 2
        kw["user_id"] = args.target
        kw["slug"] = args.slug
    result = inspector.inspect(conn, paths, **kw)
    if result is None:
        print("일치하는 항목 없음.")
        return 1
    print(inspector.format_inspect_result(result))
    return 0


def cmd_fetch(args) -> int:
    conn, paths = _open_snapshot_conn()
    if conn is None:
        return 2
    result = inspector.inspect(conn, paths, slug=args.slug)
    if result is None:
        print(f"slug `{args.slug}` 조회 실패.")
        return 1
    sample = asyncio.run(inspector.fetch_sim(paths, args.slug, n=args.n))
    if sample is None:
        print(f"config 없음 ({args.slug}) — fetch 불가.")
        return 1
    inspector.update_with_fetch_sample(result, conn, paths, sample)
    print(inspector.format_inspect_result(result))
    return 0


def cmd_diagnose(args) -> int:
    conn, paths = _open_snapshot_conn()
    if conn is None:
        return 2
    result = inspector.inspect(conn, paths, slug=args.slug)
    if result is None:
        print(f"slug `{args.slug}` 조회 실패.")
        return 1
    print(inspector.format_findings(result.findings))
    return 0


def cmd_verify(args) -> int:
    """원본 URL → 현재 dev 박스의 recognizer 로 in-memory config → fetch_list 시뮬.
    *디스크 안 건드림* (configs/, output/poll_state/ 무관) — 정리 절차 불필요.
    `--report N` 로 신고 #N 의 최근 register 잡 URL 자동 추출. --url 직접 주면 그것이 우선."""
    url = args.url
    if not url and args.report is not None:
        conn, paths = _open_snapshot_conn()
        if conn is None:
            return 2
        result = inspector.inspect(conn, paths, report_id=args.report)
        if result is None or not result.latest_job:
            print(f"신고 #{args.report} 의 최근 register 잡 못 찾음 — snapshot pull 했는지 확인.")
            return 1
        url = result.latest_job.get("url")
        if not url:
            print(f"신고 #{args.report} 의 register 잡에 url 컬럼 빔.")
            return 1
        print(f"[verify] 신고 #{args.report} 의 register 잡 URL 사용: {url}\n")
    if not url:
        print("--url 또는 --report 중 하나 필요.")
        return 2
    res = asyncio.run(inspector.verify_recognize(url, n=args.n))
    print(inspector.format_verify_result(res))
    return 0


# --------------------------------------------------------------------------- #
def main(argv) -> int:
    p = argparse.ArgumentParser(description="구독·신고 진단 (N100 snapshot 기반).")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("pull", help="N100 → 로컬 snapshot")

    p_recent = sub.add_parser("recent", help="최근 register 잡 N개")
    p_recent.add_argument("-n", type=int, default=20)

    p_reports = sub.add_parser("reports", help="신고 목록")
    p_reports.add_argument("--status", choices=["open", "resolved", "all"], default="open")
    p_reports.add_argument("-n", type=int, default=50)
    p_reports.add_argument("-v", "--verbose", action="store_true",
                            help="각 신고에 대해 풀 inspect 까지")

    p_ins = sub.add_parser("inspect", help="구독·잡·config·state 통합 dump")
    p_ins.add_argument("kind", choices=["report", "job", "slug", "user"])
    p_ins.add_argument("target", help="report id / job id / slug 문자열 / user id")
    p_ins.add_argument("--user", help="kind=slug 일 때 user_id 필터 (선택)")
    p_ins.add_argument("--slug", help="kind=user 일 때 slug (필수)")

    p_fetch = sub.add_parser("fetch", help="현 config 로 fetch_list 돌리고 진단 갱신")
    p_fetch.add_argument("slug")
    p_fetch.add_argument("-n", type=int, default=5)

    p_diag = sub.add_parser("diagnose", help="fetch 없이 정적 진단만")
    p_diag.add_argument("slug")

    p_ver = sub.add_parser(
        "verify",
        help="원본 URL → 현재 recognizer 로 in-memory cfg → fetch_list 시뮬 (디스크 안 건드림)")
    p_ver.add_argument("--url", help="검증할 원본 URL (예: 사용자가 /watch 한 URL)")
    p_ver.add_argument("--report", type=int,
                        help="신고 #N 의 최근 register 잡 URL 자동 추출")
    p_ver.add_argument("-n", type=int, default=10, help="가져올 글 개수 (기본 10)")

    a = p.parse_args(argv)
    if a.cmd == "pull":
        return cmd_pull()
    if a.cmd == "recent":
        return cmd_recent(a)
    if a.cmd == "reports":
        return cmd_reports(a)
    if a.cmd == "inspect":
        return cmd_inspect(a)
    if a.cmd == "fetch":
        return cmd_fetch(a)
    if a.cmd == "diagnose":
        return cmd_diagnose(a)
    if a.cmd == "verify":
        return cmd_verify(a)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
