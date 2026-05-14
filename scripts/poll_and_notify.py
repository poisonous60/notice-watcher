"""poll.py + notify.py 를 한 번에 (systemd notice-poll.service 가 호출).

- poll.py 가 chromium 을 띄움 (playwright_html / handwritten 사이트, 재-probe) → chromium_lock 안.
- 새 글은 collected/<ts>/<slug>.new.json + pending 큐 에 채움.
- 폴링 직후 notify.py --heartbeat 1회 — 폴링 시각(POLL_SCHEDULE) 도래분 즉시 발송 + notify_empty heartbeat.
- 추가로 별도 systemd unit (notice-notify.timer, 15분 간격) 이 notify.py --no-collected 로 다이제스트 flush —
  사용자가 폴링 시각보다 늦은 HH:MM 을 골라도 그 시각 도래 후 다음 15분 슬랏에서 발송. digest_sent cap 으로 중복 방지.
- env HEALTHCHECK_PING_URL 있으면 시작/끝에 GET ping (실패해도 무시).
- 치명적 실패 시 종료코드 != 0.

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
from bot.runtime_config import settings  # noqa: E402

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
        with chromium_lock(timeout=settings.chromium_lock.poll_timeout):
            print("[poll_and_notify] poll.py ...")
            rc = subprocess.call([PY, str(ROOT / "scripts" / "poll.py"), *argv], cwd=str(ROOT))
    except TimeoutError as e:
        print(f"[poll_and_notify] chromium 락 대기 초과 — 이번 폴링 건너뜀: {e}", file=sys.stderr)
        _ping(hc, "/fail")
        return 1
    if rc != 0:
        print(f"[poll_and_notify] poll.py 실패 rc={rc}", file=sys.stderr)
        _ping(hc, "/fail")
        return rc

    # notify.py 호출은 notice-notify.timer (15분 간격) 가 담당 — 여기선 안 함.
    _ping(hc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
