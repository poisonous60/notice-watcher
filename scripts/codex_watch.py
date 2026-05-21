"""codex 위임 run 완료 감지 — visible-window codex 는 harness 추적이 안 되므로.

codex_run.ps1 은 codex 를 보이는 창에서 콘솔로 직접 출력시킨다 (live view = 사용자용).
완료 시 codex 의 `-o, --output-last-message` 가 *결과 파일*(UTF-8 최종응답)을 쓴다.
이 스크립트는 그 결과 파일 출현을 폴링 → Claude 의 완료 감지.

진행 중 hang 은 사용자가 창으로 본다 (창이 안 자람). 이 스크립트는 완료/타임아웃만 판정.

Usage:
  python scripts/codex_watch.py <result_file>                 # 1회 검사 (exit 0=DONE 1=PENDING)
  python scripts/codex_watch.py <result_file> --loop          # DONE/TIMEOUT 까지 폴링
  python scripts/codex_watch.py <result_file> --loop --timeout 900 --sample 15
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path


def is_done(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("result_file", help="codex -o 결과 파일 경로")
    ap.add_argument("--timeout", type=int, default=900, help="--loop 시 완료 대기 한계 초 (기본 900)")
    ap.add_argument("--sample", type=int, default=15, help="--loop 폴링 간격 초 (기본 15)")
    ap.add_argument("--loop", action="store_true", help="DONE/TIMEOUT 까지 폴링")
    args = ap.parse_args(argv)

    path = Path(args.result_file)

    if not args.loop:
        if is_done(path):
            print(f"[codex_watch] DONE: {path} (size={path.stat().st_size})")
            return 0
        print(f"[codex_watch] PENDING: {path} 아직 없음")
        return 1

    start = time.time()
    while True:
        ts = time.strftime("%H:%M:%S")
        if is_done(path):
            print(f"{ts} DONE: {path} (size={path.stat().st_size})", flush=True)
            return 0
        elapsed = int(time.time() - start)
        if elapsed >= args.timeout:
            print(f"{ts} TIMEOUT: {args.timeout}s 안에 결과 안 나옴 — 창 확인(멈춤?) 또는 codex 실패", flush=True)
            return 2
        print(f"{ts} PENDING: {elapsed}s 경과 (창에서 진행 view)", flush=True)
        time.sleep(args.sample)


if __name__ == "__main__":
    raise SystemExit(main())
