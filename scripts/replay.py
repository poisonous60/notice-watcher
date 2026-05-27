"""Scoped replay — dashboard `/users` 페이지의 M2/M3 액션이 N100 에서 켠다.

흐름 (직렬, race-free):
  1. **pre-check**: `notice-poll.service` 가 active 면 fail-fast (state 파일 race 차단).
     `pgrep` 으로도 한 번 더 확인 — 타이머 사이에 manual 실행 등 systemctl 우회 경로 가드.
  2. lock 파일 (`output/.replay.lock`) 을 `O_EXCL` 로 잡기 — 동시 replay 중복 실행 차단.
  3. DELETE FROM deliveries
       - M2 (`--post-id` 지정): 그 (slug, post_id, target_id) 한 행만
       - M3 (`--post-id` 생략): (slug, target_id) 전체
  4. `output/poll_state/<slug>.json` 편집 — seen_post_ids 에서 해당 post_id 제거.
       - M2: 1개 제거. seen 에서 이미 evict 됐으면 skip + 경고 (재현 실패 가능 통지).
       - M3: 그 slug 의 seen 전체 비움 (첫페이지 모든 글 재발송 의도).
  5. `python scripts/poll.py --sites <slug>` 실행 (subprocess, inline).
  6. `python scripts/notify.py --only-target-kind <k> --only-target-id <id>` 실행 (subprocess, inline).
     - collected dir 의 새 `.new.json` 을 그 target 만 골라 발송.
  7. lock 파일 해제 (try/finally — SIGKILL 시 stale lock 가능).

사용:
    python scripts/replay.py --slug s --target-kind dm --target-id 123 --post-id p     # M2
    python scripts/replay.py --slug s --target-kind dm --target-id 123                 # M3

stdout: 각 단계별 진행 + 마지막 한 줄 JSON summary.
exit:
    0 = 모든 단계 OK
    1 = 일부 실패 (요약 참고)
    2 = 인자 또는 사전조건 실패
    3 = lock/race 충돌 (poll 활성 또는 다른 replay 진행 중)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot import db  # noqa: E402

STATE_DIR = ROOT / "output" / "poll_state"
LOCK_PATH = ROOT / "output" / ".replay.lock"

# slug = engine.slug 가 보장하는 형식. URL/파일시스템 안전 문자만.
_SLUG_RE = re.compile(r"^[A-Za-z0-9._%\-]{1,200}$")  # engine.slug 형식 — `%` 포함
# Discord snowflake — 17~19자리지만 미래 확장 대비 32자리까지 허용.
_ID_RE = re.compile(r"^[0-9]{1,32}$")


def _err(msg: str, code: int = 2) -> int:
    sys.stderr.write(f"[replay] {msg}\n")
    return code


def _poll_active() -> tuple[bool, str]:
    """`systemctl --user is-active notice-poll.service` 가 active 또는 activating 이면 True."""
    try:
        p = subprocess.run(
            ["systemctl", "--user", "is-active", "notice-poll.service"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"systemctl 확인 실패: {e}"
    state = (p.stdout or "").strip()
    return state in ("active", "activating"), state


def _poll_pgrep() -> bool:
    """fallback — manual `python scripts/poll.py` 같은 systemctl 우회 실행 감지."""
    try:
        p = subprocess.run(
            ["pgrep", "-af", "scripts/poll.py"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    # pgrep -a 는 PID + cmdline 줄 단위. 한 줄이라도 매치되면 active.
    return bool((p.stdout or "").strip())


def _acquire_lock() -> Optional[int]:
    """O_EXCL 로 lock 파일 생성. 이미 있으면 None (다른 replay 진행 중)."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return None
    os.write(fd, f"pid={os.getpid()} ts={time.time():.0f}\n".encode())
    return fd


def _release_lock(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        LOCK_PATH.unlink()
    except OSError:
        pass


def _edit_seen(slug: str, post_id: Optional[str], *, bulk: bool) -> dict:
    """state 파일에서 seen_post_ids 편집. 반환 = `{removed:int, was_present:bool, missing:bool}`.

    missing=True 면 state 파일 자체가 없음(slug 등록 안 됨) → caller 가 abort.
    bulk=True 면 seen 전부 비움 (M3).
    """
    sp = STATE_DIR / f"{slug}.json"
    if not sp.exists():
        return {"removed": 0, "was_present": False, "missing": True}
    try:
        st = json.loads(sp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return {"removed": 0, "was_present": False, "missing": True, "err": str(e)}
    seen: list[str] = list(st.get("seen_post_ids") or [])
    if bulk:
        removed = len(seen)
        st["seen_post_ids"] = []
    else:
        if post_id in seen:
            seen.remove(post_id)
            st["seen_post_ids"] = seen
            removed = 1
        else:
            removed = 0
    # 변경 없는 no-op (M2 cache miss) 면 write 생략 — mtime 보존 + 중간 실패 시 truncate risk 차단.
    if removed > 0 or bulk:
        sp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"removed": removed, "was_present": (removed > 0), "missing": False}


def _run(cmd: list[str], *, label: str) -> dict:
    """subprocess 실행. stdout/stderr 합쳐 캡처. 반환 = `{ok, rc, output}`."""
    print(f"[replay] $ {label}: {' '.join(cmd)}")
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, cwd=str(ROOT), timeout=900,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "rc": -1, "output": f"{type(e).__name__}: {e}"}
    out = (p.stdout or "") + (("\n--- stderr ---\n" + p.stderr) if p.stderr else "")
    if out.strip():
        sys.stdout.write(out)
        if not out.endswith("\n"):
            sys.stdout.write("\n")
    return {"ok": p.returncode == 0, "rc": p.returncode, "output": out[-4000:]}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="dashboard /users — scoped replay (M2/M3)")
    p.add_argument("--slug", required=True)
    p.add_argument("--target-kind", required=True, choices=("dm", "channel"))
    p.add_argument("--target-id", required=True)
    p.add_argument("--post-id", help="지정하면 M2(1행 replay), 생략하면 M3(bulk replay)")
    p.add_argument("--skip-notify", action="store_true",
                   help="poll-now 만 하고 notify --only-target 은 안 돌림 (M1 만 쓸 때).")
    a = p.parse_args(argv)

    # 인자 validation
    if not _SLUG_RE.match(a.slug):
        return _err(f"invalid slug: {a.slug!r}")
    if not _ID_RE.match(a.target_id):
        return _err(f"invalid target-id: {a.target_id!r}")
    if a.post_id is not None and not re.match(r"^[\w\-./:%,]{1,128}$", a.post_id):
        return _err(f"invalid post-id: {a.post_id!r}")

    # pre-check: poll 활성 시 fail-fast
    active, st = _poll_active()
    if active:
        return _err(f"notice-poll.service 활성 ({st}) — replay 중단. 끝나면 재시도.", code=3)
    if _poll_pgrep():
        return _err("scripts/poll.py 가 별도 프로세스로 실행 중 — replay 중단.", code=3)

    fd = _acquire_lock()
    if fd is None:
        return _err(f"lock 파일 점유 중 ({LOCK_PATH}) — 다른 replay 진행 중이거나 stale lock.", code=3)

    summary = {
        "slug": a.slug, "target_kind": a.target_kind, "target_id": a.target_id,
        "post_id": a.post_id, "bulk": a.post_id is None,
        "deliveries_deleted": 0, "seen_removed": 0, "seen_was_present": False,
        "poll": None, "notify": None, "warnings": [],
    }
    try:
        bulk = a.post_id is None
        # 1. DELETE deliveries
        conn = db.connect()
        try:
            if bulk:
                summary["deliveries_deleted"] = db.delete_deliveries_for_target(
                    conn, slug=a.slug, target_id=a.target_id)
            else:
                summary["deliveries_deleted"] = db.delete_delivery(
                    conn, slug=a.slug, post_id=a.post_id, target_id=a.target_id)
        finally:
            conn.close()
        print(f"[replay] deliveries 삭제: {summary['deliveries_deleted']} 행")

        # 2. seen_post_ids 편집
        seen_res = _edit_seen(a.slug, a.post_id, bulk=bulk)
        if seen_res.get("missing"):
            msg = f"poll_state/{a.slug}.json 없음 — 등록 안 된 slug. 중단."
            summary["warnings"].append(msg)
            return _err(msg, code=2)
        summary["seen_removed"] = seen_res["removed"]
        summary["seen_was_present"] = seen_res["was_present"]
        if not bulk and not seen_res["was_present"]:
            summary["warnings"].append(
                f"post_id={a.post_id} 가 seen_post_ids 에 없음 — 이미 cap evict 됐거나 처음부터 미관측. "
                f"poll-now 가 사이트 첫페이지에서 그 글을 다시 잡아야만 재발송됨."
            )
        print(f"[replay] seen 편집: removed={seen_res['removed']} bulk={bulk} present={seen_res['was_present']}")

        # 3. poll.py --sites <slug>
        summary["poll"] = _run(
            [sys.executable, str(ROOT / "scripts" / "poll.py"), "--sites", a.slug],
            label="poll-now",
        )
        if not summary["poll"]["ok"]:
            return _err(f"poll.py 실패 rc={summary['poll']['rc']}", code=1)

        # 4. notify.py --only-target-kind/id
        if a.skip_notify:
            summary["notify"] = {"ok": True, "rc": 0, "output": "(skipped)"}
        else:
            summary["notify"] = _run(
                [sys.executable, str(ROOT / "scripts" / "notify.py"),
                 "--only-target-kind", a.target_kind,
                 "--only-target-id", a.target_id,
                 "--no-digest"],
                label="notify-target",
            )
            if not summary["notify"]["ok"]:
                return _err(f"notify.py 실패 rc={summary['notify']['rc']}", code=1)

        print(f"[replay] done: {json.dumps({k: v for k, v in summary.items() if k not in ('poll','notify')}, ensure_ascii=False)}")
        return 0
    finally:
        _release_lock(fd)


if __name__ == "__main__":
    raise SystemExit(main())
