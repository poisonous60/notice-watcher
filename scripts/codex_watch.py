"""codex 위임 run 완료 감지 — visible-window codex 는 harness 추적이 안 되므로.

codex_run.ps1 은 codex 를 보이는 창에서 콘솔로 직접 출력시킨다 (live view = 사용자용).
완료 시 codex 의 `-o, --output-last-message` 가 *결과 파일*(UTF-8 최종응답)을 쓴다.
이 스크립트는 그 결과 파일 출현을 폴링 → Claude 의 완료 감지.

진행 중 hang 은 사용자가 창으로 본다 (창이 안 자람). 이 스크립트는 완료/타임아웃만 판정.

Usage:
  python scripts/codex_watch.py <result_file>                 # 1회 검사 (exit 0=DONE 1=PENDING)
  python scripts/codex_watch.py <result_file> --loop          # DONE/TIMEOUT 까지 폴링
  python scripts/codex_watch.py <result_file> --loop --timeout 900 --sample 15
  python scripts/codex_watch.py <r1> <r2> ... --loop          # 여러 result 한 번에 (전부 DONE 까지) — batch wave 권장

배치 wave 위임 시: result 파일별로 watcher 를 따로 띄우지 말 것. 여러 result 를 한 명령에
넘겨 *하나의* watcher 로 묶고, 그 한 명령을 harness 의 백그라운드 실행으로 돌린다.
⚠ shell `&` 로 백그라운드 띄우면 호출 종료 시 프로세스가 죽어 완료 알림이 안 온다 — 반드시
harness 백그라운드(run_in_background) 사용. (2026-05-22 batch 에서 shell `&` watcher 유실 관측.)
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path


def is_done(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("result_file", nargs="+", help="codex -o 결과 파일 경로 (여러 개 = batch wave 한 번에)")
    ap.add_argument("--timeout", type=int, default=900, help="--loop 시 완료 대기 한계 초 (기본 900)")
    ap.add_argument("--sample", type=int, default=15, help="--loop 폴링 간격 초 (기본 15)")
    ap.add_argument("--loop", action="store_true", help="DONE/TIMEOUT 까지 폴링")
    args = ap.parse_args(argv)

    paths = [Path(p) for p in args.result_file]

    if not args.loop:
        pending = [p for p in paths if not is_done(p)]
        for p in paths:
            print(f"[codex_watch] {'DONE' if is_done(p) else 'PENDING'}: {p}")
        return 0 if not pending else 1

    start = time.time()
    while True:
        ts = time.strftime("%H:%M:%S")
        done = [p for p in paths if is_done(p)]
        if len(done) == len(paths):
            print(f"{ts} ALL DONE: {len(done)}/{len(paths)}", flush=True)
            for p in paths:
                print(f"  DONE {p} (size={p.stat().st_size})", flush=True)
            return 0
        elapsed = int(time.time() - start)
        if elapsed >= args.timeout:
            print(f"{ts} TIMEOUT: {args.timeout}s — {len(done)}/{len(paths)} DONE. 미완 창 확인(멈춤?) 또는 codex 실패", flush=True)
            for p in paths:
                if not is_done(p):
                    print(f"  PENDING {p}", flush=True)
            return 2
        print(f"{ts} PENDING: {len(done)}/{len(paths)} DONE, {elapsed}s 경과 (창에서 진행 view)", flush=True)
        time.sleep(args.sample)


if __name__ == "__main__":
    raise SystemExit(main())
