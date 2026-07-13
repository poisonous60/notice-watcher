"""Live page fetcher for the register agentic mode (budget-limited).

Used by the codex agent (from inside its tmpdir) to look at a real page's DOM
when the staged digest snapshots are stale or mis-picked (probe sometimes
samples the wrong "first article"). Reuses the probe fetch stack — header
presets / stealth playwright / polite sleep — instead of hand-rolled requests.

Usage:
    python scripts/fetch_page.py <url>            # static httpx GET (Chrome headers)
    python scripts/fetch_page.py <url> --render   # stealth playwright rendered DOM

Output: one JSON line on stdout
    {"ok": true, "status": 200, "chars": 48213, "path": "./fetched_1.html",
     "fetches_used": 1, "fetches_left": 4}
Compressed DOM (same compression as digest.json snapshots) is written to
./fetched_<n>.html next to this script; raw artifacts land in ./fetch_<n>/.

Budget: MAX_FETCHES attempts per tmpdir, tracked in ./fetch_count.txt next to
this script. Every attempt counts (success or failure) so a dead host cannot
be hammered. The gate runs before any probe import.

The script must be runnable both:
- from the repo root (developer smoke usage)
- from an agent tmpdir (agent has copy in cwd, repo on PYTHONPATH)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

MAX_FETCHES = 5

_HERE = Path(__file__).resolve().parent
_COUNT_PATH = _HERE / "fetch_count.txt"  # __file__ 기준 — 에이전트가 서브디렉토리에서 실행해도 동일


def _emit(payload: dict) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


def _read_count() -> int:
    try:
        return int(_COUNT_PATH.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        return 0


def _bootstrap_repo_path() -> None:
    # validate_config.py 와 동일한 해석 순서: 부모가 repo → REPO_ROOT env → repo_path.txt.
    repo_root = _HERE.parent
    if (repo_root / "probe").is_dir():
        sys.path.insert(0, str(repo_root))
        return
    repo_from_env = os.environ.get("REPO_ROOT", "").strip()
    if repo_from_env and Path(repo_from_env).is_dir():
        sys.path.insert(0, repo_from_env)
        return
    repo_hint = _HERE / "repo_path.txt"
    if repo_hint.exists():
        repo_path = repo_hint.read_text(encoding="utf-8").strip()
        if repo_path and Path(repo_path).is_dir():
            sys.path.insert(0, repo_path)


def main(argv: list[str] | None = None) -> int:
    # 예산 게이트 — probe import 전. 6번째 시도부터 무조건 거부.
    count = _read_count()
    if count >= MAX_FETCHES:
        _emit({"ok": False, "error": f"fetch budget exhausted ({MAX_FETCHES}/{MAX_FETCHES})",
               "fetches_used": count, "fetches_left": 0})
        return 3

    ap = argparse.ArgumentParser(description="fetch one URL's DOM (agentic register tool)")
    ap.add_argument("url")
    ap.add_argument("--render", action="store_true",
                    help="stealth playwright 로 렌더된 DOM (기본: httpx 정적 GET)")
    ap.add_argument("--max-chars", type=int, default=60_000,
                    help="압축 DOM 출력 상한 (digest 스냅샷과 동일 기본값)")
    args = ap.parse_args(argv)

    n = count + 1
    _COUNT_PATH.write_text(str(n), encoding="utf-8")  # 시도 즉시 소진 — 실패해도 예산 차감

    _bootstrap_repo_path()
    from engine.digest import compress_html_for_prompt  # noqa: E402
    from probe.polite import polite_sleep  # noqa: E402

    raw_dir = _HERE / f"fetch_{n}"
    raw_dir.mkdir(exist_ok=True)
    polite_sleep()

    status = None
    error = None
    html = None
    try:
        if args.render:
            from probe.fetch_headless import fetch_with_capture  # noqa: E402
            res = fetch_with_capture(url=args.url, out_dir=raw_dir, target="page", headless=True)
            status = res.status
            error = res.error
            body_path = raw_dir / "page.html"
            if body_path.is_file():
                html = body_path.read_text(encoding="utf-8", errors="replace")
        else:
            from probe.fetch_static import fetch  # noqa: E402
            from probe.headers import all_presets  # noqa: E402
            res = fetch(strategy="agent_fetch", target="page", url=args.url,
                        headers=all_presets(args.url)["H3"], out_dir=raw_dir, body_name="page")
            status = res.status
            error = res.error
            if res.body_path:
                html = Path(res.body_path).read_text(encoding="utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001 — 에이전트에겐 JSON 한 줄이 유일한 인터페이스
        error = f"{type(e).__name__}: {e}"

    out: dict = {"ok": False, "status": status,
                 "fetches_used": n, "fetches_left": MAX_FETCHES - n}
    if html:
        compressed = compress_html_for_prompt(html)[: args.max_chars]
        out_path = _HERE / f"fetched_{n}.html"
        out_path.write_text(compressed, encoding="utf-8")
        out.update(ok=True, chars=len(compressed), path=f"./fetched_{n}.html")
    if error:
        out["error"] = error
    _emit(out)
    return 0 if html else 2


if __name__ == "__main__":
    sys.exit(main())
