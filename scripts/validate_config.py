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
import sys
from pathlib import Path

# Make the repo importable when the script is copied to an agent tmpdir.
# Heuristic: if `engine` / `generate` not importable, look for a sibling
# `repo_path.txt` (parent process writes this).
_HERE = Path(__file__).resolve().parent
try:
    from generate.validate import validate_built_config  # type: ignore
except ImportError:
    repo_hint = _HERE / "repo_path.txt"
    if repo_hint.exists():
        repo_path = repo_hint.read_text(encoding="utf-8").strip()
        if repo_path and Path(repo_path).is_dir():
            sys.path.insert(0, repo_path)
    from generate.validate import validate_built_config  # type: ignore  # noqa: E402


def _emit_error(reason: str, *, rc: int = 2) -> int:
    json.dump({"ok": False, "error": reason, "checks": [], "sample_posts": []},
              sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return rc


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
    try:
        rep = asyncio.run(validate_built_config(cfg, digest=None, fetch_articles=1))
    except Exception as e:  # noqa: BLE001 — any exception during validate is a soft fail (signal to agent)
        return _emit_error(f"validate raised: {type(e).__name__}: {e}")
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
