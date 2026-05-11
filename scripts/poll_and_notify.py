"""poll.py → notify.py 를 한 번에 (systemd notice-poll.service 가 실행).

- poll.py 가 chromium 을 띄울 수 있으므로(playwright_html / handwritten 사이트, 재-probe) chromium_lock 안에서.
- notify.py 는 Gemini + Discord 뿐이라 락 밖.
- env HEALTHCHECK_PING_URL 있으면 시작/끝에 GET ping (Healthchecks.io 등 — 실패해도 무시).
- 치명적 실패 시 종료코드 != 0 (systemd 가 로그 + 필요시 OnFailure 처리).

사용:
    python scripts/poll_and_notify.py
    python scripts/poll_and_notify.py --max-new-articles 5     # poll.py 로 그대로 전달
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._chromium_lock import chromium_lock  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable


def _ping(url: str | None, suffix: str = "") -> None:
    if not url:
        return
    try:
        import httpx

        httpx.get(url + suffix, timeout=10.0)
    except Exception:  # noqa: BLE001
        pass


def main(argv: list[str]) -> int:
    import os

    hc = os.environ.get("HEALTHCHECK_PING_URL", "").strip() or None
    _ping(hc, "/start")

    rc = 0
    try:
        with chromium_lock(timeout=1800.0):
            print("[poll_and_notify] poll.py ...")
            rc = subprocess.call([PY, str(ROOT / "scripts" / "poll.py"), *argv], cwd=str(ROOT))
    except TimeoutError as e:
        print(f"[poll_and_notify] chromium 락 대기 초과 — 이번 폴링 건너뜀: {e}", file=sys.stderr)
        _ping(hc, "/fail")
        return 1
    if rc != 0:
        print(f"[poll_and_notify] poll.py 실패 rc={rc} — notify 생략", file=sys.stderr)
        _ping(hc, "/fail")
        return rc

    print("[poll_and_notify] notify.py ...")
    # --heartbeat: 방금 폴링했으므로, notify_empty=1 인 realtime 구독에 새 글 없으면 '새 공지 없음' 1줄
    rc = subprocess.call([PY, str(ROOT / "scripts" / "notify.py"), "--heartbeat"], cwd=str(ROOT))
    if rc != 0:
        print(f"[poll_and_notify] notify.py 실패 rc={rc}", file=sys.stderr)
        _ping(hc, "/fail")
        return rc

    _ping(hc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
