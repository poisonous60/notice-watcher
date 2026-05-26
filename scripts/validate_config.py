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
import json
import os
import signal
import sys
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


INTERNAL_TIMEOUT_S = 40.0


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


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        return _emit_error(f"usage: {argv[0]} <candidate.json>")
    candidate_path = Path(argv[1])
    if not candidate_path.exists():
        return _emit_error(f"candidate not found: {candidate_path}")
    try:
        cfg = json.loads(candidate_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return _emit_error(f"candidate JSON parse failed: {type(e).__name__}: {e}")
    if not isinstance(cfg, dict):
        return _emit_error(f"candidate JSON is not an object, got {type(cfg).__name__}")
    old_alarm = _install_hard_timeout(INTERNAL_TIMEOUT_S)
    try:
        rep = asyncio.run(_run_with_timeout(cfg))
    except (asyncio.TimeoutError, _HardTimeout):
        return _emit_error(f"validate_internal_timeout_{int(INTERNAL_TIMEOUT_S)}s", rc=0)
    except Exception as e:  # noqa: BLE001 — any exception during validate is a soft fail (signal to agent)
        return _emit_error(f"validate raised: {type(e).__name__}: {e}")
    finally:
        _clear_hard_timeout(old_alarm)
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
