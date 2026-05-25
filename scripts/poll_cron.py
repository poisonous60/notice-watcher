"""폴링 1회 (systemd notice-poll.service 가 호출). poll.py subprocess + healthcheck ping wrapper.

ADR 0019 Phase 2 (i) — 옛 이름 `poll_and_notify.py` 에서 rename. 발송은 이미 ADR 0006 에서 분리됨
(bot/delivery_tick.py 1분 tick → scripts/deliver_due.py) — 이 wrapper 는 더 이상 notify 안 함.

- poll.py 가 chromium 을 띄움 (playwright_html / handwritten 사이트, 재-probe) → poll.py 내부에서
  사이트별로 `chromium_lock_async(slots=settings.chromium_lock.slots)` 잡음 (ADR 0019 Phase 1).
  이 wrapper 자체는 lock 안 잡음 — 옛 outer wrapper 는 새 per-site lock 과 self-deadlock (parent
  가 slot 통째 점유) 라 ADR 0019 Phase 1 에서 제거됨.
- 새 글은 posts 캐시 + collected/<ts>/<slug>.new.json 에 떨어짐.
- env HEALTHCHECK_PING_URL 있으면 시작/끝에 GET ping (실패해도 무시).
- 치명적 실패 시 종료코드 != 0.

사용:
    python scripts/poll_cron.py
    python scripts/poll_cron.py --max-new-articles 5     # poll.py 로 그대로 전달
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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

    with start_trace("poll_cron", attrs={"argv": list(argv)}) as tr:
        # ADR 0019 Phase 1 — 옛 outer chromium_lock wrapper 제거. poll.py 가 사이트별로 잡음.
        # outer wrapper 가 살아있으면 parent 가 slot 1개 통째 점유 → child poll.py 가 N=1 일 때
        # 영원히 timeout, N≥2 일 때도 capacity 1 낭비.
        with tr.span("poll_subprocess"):
            print("[poll_cron] poll.py ...")
            child_env = {**os.environ, **env_for_child()}
            rc = subprocess.call(
                [PY, str(ROOT / "scripts" / "poll.py"), *argv],
                cwd=str(ROOT), env=child_env,
            )
        if rc != 0:
            print(f"[poll_cron] poll.py 실패 rc={rc}", file=sys.stderr)
            _ping(hc, "/fail")
            return rc

        # ADR 0006 — 폴링/발송 분리. poll.py 가 새 글을 posts 캐시에 박는 것으로 끝.
        # 실제 요약·필터·발송은 봇 내부 1분 tick → scripts/deliver_due.py 가 사용자 발송 시각에 처리.
        _ping(hc)
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
