"""poll.py + notify.py 를 한 번에 (systemd notice-poll.service 가 호출).

- poll.py 가 chromium 을 띄움 (playwright_html / handwritten 사이트, 재-probe) → chromium_lock 안.
- 새 글은 collected/<ts>/<slug>.new.json 에 떨어짐.
- 폴링 직후 notify.py --no-digest 1회 — collected 새 글을 즉시 요약/필터/Discord 발송 (모든 구독 realtime).
- notice-notify.timer (15분 간격) 는 retry 용도: .notified 마커 작성 실패한 collected dir 나
  옛 다이제스트(HH:MM) 시절의 pending 잔재만 처리. 정상 흐름에서 할 일 없음.
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
from engine.tracing import start_trace, env_for_child  # noqa: E402

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

    with start_trace("poll_and_notify", attrs={"argv": list(argv)}) as tr:
        rc = 0
        try:
            with tr.span("chromium_lock_acquire"):
                lock_ctx = chromium_lock(timeout=settings.chromium_lock.poll_timeout,
                                         slots=settings.chromium_lock.slots)
                lock_ctx.__enter__()
            try:
                with tr.span("poll_subprocess"):
                    print("[poll_and_notify] poll.py ...")
                    child_env = {**os.environ, **env_for_child()}
                    rc = subprocess.call(
                        [PY, str(ROOT / "scripts" / "poll.py"), *argv],
                        cwd=str(ROOT), env=child_env,
                    )
            finally:
                lock_ctx.__exit__(None, None, None)
        except TimeoutError as e:
            print(f"[poll_and_notify] chromium 락 대기 초과 — 이번 폴링 건너뜀: {e}", file=sys.stderr)
            _ping(hc, "/fail")
            return 1
        if rc != 0:
            print(f"[poll_and_notify] poll.py 실패 rc={rc}", file=sys.stderr)
            _ping(hc, "/fail")
            return rc

        # collected 새 글 즉시 처리 (digest flush 는 notice-notify.timer 15분 슬랏이 마저 담당).
        with tr.span("notify_subprocess"):
            print("[poll_and_notify] notify.py --no-digest ...")
            child_env = {**os.environ, **env_for_child()}
            nrc = subprocess.call(
                [PY, str(ROOT / "scripts" / "notify.py"), "--no-digest", "--heartbeat"],
                cwd=str(ROOT), env=child_env,
            )
        if nrc != 0:
            print(f"[poll_and_notify] notify.py 실패 rc={nrc}", file=sys.stderr)
            _ping(hc, "/fail")
            return nrc

        _ping(hc)
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
