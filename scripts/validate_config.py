"""validate_built_config CLI wrapper for the register agentic mode.

Used by the codex agent (from inside its tmpdir) to validate a candidate
config without needing inline Python. Outputs the validation result as JSON
on stdout.

Usage:
    python scripts/validate_config.py <candidate_path.json>

The script must be runnable both:
- from the repo root (api_loop developer usage / tests)
- from an agent tmpdir (agent has copy in cwd, repo on PYTHONPATH)
"""
from __future__ import annotations

import asyncio
import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path

# Make the repo importable when the script is copied to an agent tmpdir.
# Resolution order: REPO_ROOT env (set by codex_agentic.run_codex_agentic) →
# sibling `repo_path.txt` → direct import (when run from repo root).
_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
if (_REPO_ROOT / "generate").is_dir():
    sys.path.insert(0, str(_REPO_ROOT))
try:
    from generate.validate import validate_built_config  # type: ignore
    from engine.tracing import start_trace  # type: ignore
except ImportError:
    repo_from_env = os.environ.get("REPO_ROOT", "").strip()
    if repo_from_env and Path(repo_from_env).is_dir():
        sys.path.insert(0, repo_from_env)
    else:
        repo_hint = _HERE / "repo_path.txt"
        if repo_hint.exists():
            repo_path = repo_hint.read_text(encoding="utf-8").strip()
            if repo_path and Path(repo_path).is_dir():
                sys.path.insert(0, repo_path)
    from generate.validate import validate_built_config  # type: ignore  # noqa: E402
    from engine.tracing import start_trace  # type: ignore  # noqa: E402

_OUTPUT_ROOT = Path(os.environ.get("REPO_ROOT") or _REPO_ROOT)

# Keep this below the outer agentic/register wall budgets. Validator speed comes
# from bounding work per candidate, not stretching this ceiling.
INTERNAL_TIMEOUT_S = 25.0


class _HardTimeout(TimeoutError):
    pass


def _emit_error(reason: str, *, rc: int = 2) -> int:
    json.dump({"ok": False, "error": reason, "checks": [], "sample_posts": []},
              sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return rc


async def _run_with_timeout(cfg: dict):
    return await asyncio.wait_for(
        validate_built_config(cfg, digest=None, fetch_articles=1),
        timeout=INTERNAL_TIMEOUT_S,
    )


def _slug_for_timing(candidate_path: Path, cfg: dict) -> str:
    stem = candidate_path.stem.strip()
    if stem and stem != "candidate":
        return stem
    site = str(cfg.get("site") or "site").strip().strip("/").replace("://", "_")
    board = str(cfg.get("board") or "root").strip() or "root"
    safe = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in f"{site}_{board}")
    return safe[:120] or "candidate"


def _dump_timing(trace, *, cfg: dict, candidate_path: Path, status: str, error: str | None,
                 started: float, started_wall: float, out_dir: Path | None = None) -> Path | None:
    if not getattr(trace, "enabled", False):
        return None
    target = out_dir or (_OUTPUT_ROOT / "output" / "validate_timing")
    target.mkdir(parents=True, exist_ok=True)
    slug = _slug_for_timing(candidate_path, cfg)
    strategy = str(cfg.get("strategy") or "unknown")
    ts = time.strftime("%Y%m%dT%H%M%S", time.localtime(started_wall))
    spans = []
    for sp in getattr(trace, "_spans", []):
        spans.append({
            "name": sp.name,
            "duration_ms": sp.duration_ms,
            "ok": sp.ok,
            "err": sp.err,
            "attrs": sp.attrs,
            "parent_id": sp.parent_id,
            "span_id": sp.span_id,
        })
    payload = {
        "slug": slug,
        "candidate_path": str(candidate_path),
        "strategy": strategy,
        "status": status,
        "error": error,
        "total_ms": (time.perf_counter() - started) * 1000.0,
        "trace_id": getattr(trace, "trace_id", None),
        "spans": spans,
    }
    path = target / f"{slug}__{strategy}__{ts}.json"
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return None
    return path


def _install_hard_timeout(timeout_s: float):
    """POSIX watchdog for sync blocks that prevent asyncio.wait_for from firing."""
    if not hasattr(signal, "SIGALRM") or not hasattr(signal, "setitimer"):
        return None
    old_handler = signal.getsignal(signal.SIGALRM)

    def _raise_timeout(_signum, _frame):
        raise _HardTimeout

    signal.signal(signal.SIGALRM, _raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, max(1.0, float(timeout_s)))
    return old_handler


def _clear_hard_timeout(old_handler) -> None:
    if old_handler is None:
        return
    signal.setitimer(signal.ITIMER_REAL, 0.0)
    signal.signal(signal.SIGALRM, old_handler)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Validate a generated config and print JSON on stdout.")
    p.add_argument("candidate", help="candidate config JSON")
    p.add_argument("--verbose-timing", action="store_true",
                   help="write timing spans to output/validate_timing without changing stdout JSON")
    p.add_argument("--strategy", choices=["httpx_html", "playwright_html", "auto"],
                   help="temporarily override cfg.strategy for comparison runs")
    p.add_argument("--timing-dir", help=argparse.SUPPRESS)
    return p.parse_args(argv[1:])


def main(argv: list[str]) -> int:
    try:
        args = _parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    candidate_path = Path(args.candidate)
    if not candidate_path.exists():
        return _emit_error(f"candidate not found: {candidate_path}")
    try:
        cfg = json.loads(candidate_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return _emit_error(f"candidate JSON parse failed: {type(e).__name__}: {e}")
    if not isinstance(cfg, dict):
        return _emit_error(f"candidate JSON is not an object, got {type(cfg).__name__}")
    if args.strategy and args.strategy != "auto":
        cfg = {**cfg, "strategy": args.strategy}
    verbose_timing = args.verbose_timing or os.environ.get("VALIDATE_TIMING", "").strip().lower() in ("1", "true", "yes", "on")
    started = time.perf_counter()
    started_wall = time.time()
    status = "ok"
    err_text = None
    trace_cm = start_trace("validate_config", attrs={
        "candidate": str(candidate_path),
        "strategy": cfg.get("strategy"),
    }) if verbose_timing else None
    trace = trace_cm.__enter__() if trace_cm is not None else None
    old_alarm = _install_hard_timeout(INTERNAL_TIMEOUT_S)
    try:
        try:
            rep = asyncio.run(_run_with_timeout(cfg))
        except (asyncio.TimeoutError, _HardTimeout):
            status = "timeout"
            err_text = f"validate_internal_timeout_{int(INTERNAL_TIMEOUT_S)}s"
            return _emit_error(err_text, rc=0)
        except Exception as e:  # noqa: BLE001 — any exception during validate is a soft fail (signal to agent)
            status = "error"
            err_text = f"validate raised: {type(e).__name__}: {e}"
            return _emit_error(err_text)
    finally:
        _clear_hard_timeout(old_alarm)
        if trace_cm is not None:
            _dump_timing(
                trace,
                cfg=cfg,
                candidate_path=candidate_path,
                status=status,
                error=err_text,
                started=started,
                started_wall=started_wall,
                out_dir=Path(args.timing_dir) if args.timing_dir else None,
            )
            trace_cm.__exit__(None, None, None)
    out = {
        "ok": rep.ok,
        "n_posts": rep.n_posts,
        "checks": [{"name": c.name, "ok": c.ok, "hard": c.hard, "detail": c.detail} for c in rep.checks],
        "sample_posts": rep.sample_posts,
        "article_bodies": rep.article_bodies,
        "error": rep.error,
    }
    json.dump(out, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
