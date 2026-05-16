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


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="notice-watcher dev박스 대시보드")
    p.add_argument("--host", default="127.0.0.1",
                   help="바인딩 호스트 (기본 127.0.0.1 — 외부에 절대 0.0.0.0 쓰지 말 것)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--reload", action="store_true", help="개발용 자동 reload (uvicorn --reload)")
    a = p.parse_args(argv)

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
