"""dev박스 전용 로컬 웹 대시보드 — `python scripts/dashboard.py`.

127.0.0.1:8765 에 바인딩. 외부 노출 X. 의존성은 `requirements-dashboard.txt`.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Timings/Usage 탭 무용 방지 — dashboard 호출은 거의 항상 trace 보고 싶음. 끄고 싶으면 `TRACE_ENABLED=0`.
os.environ.setdefault("TRACE_ENABLED", "1")


def _require_deploy_host_env() -> None:
    """DEPLOY_HOST 없으면 startup 거부.

    Why: 없으면 dashboard 는 뜨지만 모든 페이지가 N100 snapshot pull 에 RuntimeError → "Pull 실패 — stale 데이터"
    badge 만 표시되고 snapshot 은 영원히 옛 시각에 머무름 (2026-05-23 발생). 사용자가 알아채려면 페이지를 열어
    badge 호버해야 보여 무성하게 silent fail. startup 에서 즉시 거부해 다음 사람이 안 트게 게이트 박음.
    """
    if os.environ.get("DEPLOY_HOST"):
        return
    sys.stderr.write(
        "[dashboard] DEPLOY_HOST 환경변수가 없습니다 — 운영 호스트 snapshot pull 이 모두 실패합니다.\n"
        "  PowerShell: $env:DEPLOY_HOST = 'user@host'; python scripts/dashboard.py --reload\n"
        "  bash:       DEPLOY_HOST=user@host python scripts/dashboard.py --reload\n"
    )
    sys.exit(2)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="notice-watcher dev박스 대시보드")
    p.add_argument("--host", default="127.0.0.1",
                   help="바인딩 호스트 (기본 127.0.0.1 — 외부에 절대 0.0.0.0 쓰지 말 것)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--reload", action="store_true", help="개발용 자동 reload (uvicorn --reload)")
    p.add_argument("--self-check", action="store_true", help="라우트 import smoke test 후 종료")
    a = p.parse_args(argv)

    if a.self_check:
        try:
            from dashboard.app import app
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"[dashboard] self-check FAIL: import dashboard.app: {type(e).__name__}: {e}\n")
            return 1
        paths = {getattr(r, "path", "") for r in app.routes}
        needed = {"/jobs", "/usage", "/probe-har"}
        missing = sorted(needed - paths)
        if missing:
            sys.stderr.write(f"[dashboard] self-check FAIL: missing routes {missing}\n")
            return 1
        print("[dashboard] self-check OK: dashboard.app import + /jobs,/usage,/probe-har routes")
        return 0

    _require_deploy_host_env()

    try:
        import uvicorn
    except ImportError:
        sys.stderr.write(
            "[dashboard] 의존성 미설치 — `pip install -r requirements-dashboard.txt` 먼저.\n")
        return 2

    print(f"[dashboard] http://{a.host}:{a.port}  (Ctrl+C 로 종료)")
    uvicorn.run(
        "dashboard.app:app",
        host=a.host, port=a.port, reload=a.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
