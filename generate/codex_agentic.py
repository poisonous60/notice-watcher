"""Codex agentic mode for the `config_generate` call_site.

Replaces the 4-retry API loop (`generate_config_validated`) with a single
multi-turn codex agent session. The agent has read access to the entire repo
(prior-art lookup) and writes a *candidate* config to its tmpdir. The parent
process **re-validates** the candidate independently and atomically publishes
it to `configs/<slug>.json`.

Trust boundary (rev 4 — see `output/plan_register_agentic.md`):
- On Linux, run Codex with `workspace-write` sandbox rooted at the tmpdir so
  repo writes are blocked before audit. On Windows the codex sandbox blocks all
  `workspace-write` shell commands (empirically — see
  `scripts/experiments/codex_sandbox_probe.py`), so Windows keeps the bypass
  fallback and relies on SHA256+mtime audit to detect any out-of-bounds write.
- Agent MAY only write to its tmpdir. Repo write of ANY kind (including
  `configs/<slug>.json`) → AUDIT_FAIL → `.BUG.json` (system violation).
- Parent always reads `tmpdir/candidate.json`, runs `validate_built_config`,
  and atomically publishes via `Path.replace`.

Hard caps:
- Wall-clock subprocess timeout (default 180s).
- Per-cycle hint (3 validate cycles) — enforced by prompt, validated via
  agent JSON `attempts[]`.

Errors raised by `run_codex_agentic`:
- `LLMNetworkError`     — subprocess timeout / codex CLI not found.
- `LLMQuotaError`       — codex auth/quota error (stderr pattern match).
- `LLMHttpError`        — codex non-zero exit without quota marker.
- `LLMParseError`       — agent output not parseable per schema.
- `GenerationError`     — agent emitted ok=false OR parent re-validate failed.
- `AuditFailError`      — SHA audit detected out-of-tmpdir write. **Treated as
                          `.BUG.json` (system violation) — NOT site fault.**
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from .llm_base import (
    LLMError, LLMNetworkError, LLMQuotaError, LLMHttpError, LLMParseError,
)
from .validate import ValidationReport, validate_built_config

try:
    from generate.codex import _classify_error as _codex_base_classify_error, _codex_bin
except ImportError:  # codex.py not on path in some test setups
    from .codex import _classify_error as _codex_base_classify_error, _codex_bin  # type: ignore

try:
    from engine.digest import compress_html_for_prompt as _compress_html
except ImportError:
    _compress_html = None


# --- public constants --------------------------------------------------------

DEFAULT_TIMEOUT_S = 180.0
DEFAULT_MAX_CYCLES = 3

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schemas" / "register_agentic_result.json"
PROMPT_USER_PATH = REPO_ROOT / "prompts" / "register_agent_user.txt"
PROMPT_AGENTS_PATH = REPO_ROOT / "prompts" / "register_agent_AGENTS.md"
VALIDATE_WRAPPER_PATH = REPO_ROOT / "scripts" / "validate_config.py"
_AUDIT_POPEN = subprocess.Popen


VALIDATOR_ATTEMPT_LOGGER = r'''from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_slug() -> str:
    for raw in (Path(a).stem for a in sys.argv[2:] if a):
        if raw and raw != "candidate":
            return raw[:80]
    return "candidate"


def _new_path() -> Path:
    target = Path(os.environ.get("VALIDATE_TIMING_DIR") or "validate_timing")
    ts = time.strftime("%Y%m%dT%H%M%S", time.localtime())
    name = f"agentic_attempt__{_safe_slug()}__{ts}__pid{os.getpid()}__ppid{os.getppid()}.json"
    return target / name


def _payload(status: str, *, rc: int | None = None, argv_start: int = 2) -> dict:
    now = time.time()
    return {
        "type": "agentic_validator_attempt",
        "status": status,
        "rc": rc,
        "wall_time": now,
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "cwd": os.getcwd(),
        "argv": sys.argv[argv_start:],
        "repo_root": os.environ.get("REPO_ROOT"),
        "validate_timing_dir": os.environ.get("VALIDATE_TIMING_DIR"),
    }


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "start":
        path = _new_path()
        payload = _payload("started")
        payload["started_wall"] = payload["wall_time"]
        _write(path, payload)
        print(path)
        return 0
    if mode == "start-path":
        if len(sys.argv) < 3:
            return 2
        path = Path(sys.argv[2])
        payload = _payload("started", argv_start=3)
        payload["started_wall"] = payload["wall_time"]
        _write(path, payload)
        print(path)
        return 0
    if mode == "end":
        if len(sys.argv) < 4:
            return 2
        path = Path(sys.argv[2])
        try:
            rc = int(sys.argv[3])
        except ValueError:
            rc = None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}
        end_payload = _payload("ended", rc=rc)
        started_wall = payload.get("started_wall")
        if isinstance(started_wall, (int, float)):
            end_payload["total_ms"] = (end_payload["wall_time"] - float(started_wall)) * 1000.0
        payload.update(end_payload)
        _write(path, payload)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
'''


# --- errors ------------------------------------------------------------------


class GenerationError(LLMError):
    """Agent failed to produce a passing config (max_cycles / agent_gave_up / parent re-validate fail).

    Carries token/wall meta even on failure so callers can log cost of failed
    runs (measurement parity with success path).
    """

    def __init__(self, msg: str, *, last_config: Optional[dict] = None,
                 last_feedback: str = "",
                 prompt_tokens: int = 0, completion_tokens: int = 0,
                 wall_s: float = 0.0, stop_reason: str = "",
                 codex_version: str = "") -> None:
        super().__init__(msg)
        self.last_config = last_config
        self.last_feedback = last_feedback
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.wall_s = wall_s
        self.stop_reason = stop_reason
        self.codex_version = codex_version


class AuditFailError(LLMError):
    """Agent wrote outside its tmpdir. System violation → `.BUG.json`."""

    def __init__(self, msg: str, *, violations: list[str]) -> None:
        super().__init__(msg)
        self.violations = violations


# --- audit -------------------------------------------------------------------


@dataclass(frozen=True)
class _AuditEntry:
    sha256: str
    size: int
    mtime_ns: int


def _audit_path_is_ignored(path: Path) -> bool:
    """Runtime cache files can change as a side effect of Python/tooling startup."""
    name = path.name
    if name in (".DS_Store", "Thumbs.db"):
        return True
    if name.endswith((".pyc", ".pyo")):
        return True
    parts = set(path.parts)
    return bool(parts & {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"})


def _sha_of(path: Path, *, chunk: int = 1 << 16) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _audit_snapshot_paths(repo: Path, slug: str) -> dict[str, _AuditEntry]:
    """SHA256+size+mtime snapshot of all files under guarded dirs at THIS moment.

    Recomputes the file list each call (instead of taking a precomputed list)
    so NEW files created by the agent are detected — without this, an agent
    that creates a brand-new file under a guarded dir would slip past audit
    because the file wasn't in any prior `paths` iteration.
    """
    out: dict[str, _AuditEntry] = {}
    for p in _iter_audit_paths(repo, slug):
        if _audit_path_is_ignored(p):
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        if not p.is_file():
            continue
        try:
            sha = _sha_of(p)
        except OSError:
            continue
        out[str(p)] = _AuditEntry(sha256=sha, size=st.st_size, mtime_ns=st.st_mtime_ns)
    # Additionally, scan a few directories for NEW files outside the precomputed
    # list (e.g. agent creates a new file under configs/ that wasn't there before).
    # The guarded dirs as a set:
    extra_dirs = [
        repo / "engine", repo / "prompts", repo / "scripts", repo / "bot",
        repo / "dashboard", repo / "tests", repo / "docs", repo / "messages",
        repo / "schemas", repo / "configs", repo / "output" / "poll_state",
        repo / "output" / "probe" / slug,
    ]
    for d in extra_dirs:
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if not p.is_file():
                continue
            if _audit_path_is_ignored(p):
                continue
            key = str(p)
            if key in out:
                continue
            # Snapshot ALL configs/ files. _audit_diff applies the per-slug policy:
            # other-slug NEW is allowed (parallel agent publish — rev 5), but DELETE
            # or CONTENT CHANGED of other-slug configs is a violation (closes the hole
            # where an agent could delete few-shot example configs or corrupt other
            # slugs' settled configs and slip past audit).
            if p.parent == repo / "output" / "poll_state" and not p.name.startswith(f"{slug}."):
                continue
            try:
                st = p.stat()
                sha = _sha_of(p)
            except OSError:
                continue
            out[key] = _AuditEntry(sha256=sha, size=st.st_size, mtime_ns=st.st_mtime_ns)
    return out


def _audit_git_command(repo: Path, args: list[str], *, capture: bool = True,
                       text: bool = True) -> tuple[int, str, str]:
    proc = _AUDIT_POPEN(
        ["git", *args],
        cwd=repo,
        text=text,
        encoding="utf-8" if text else None,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
    )
    stdout, stderr = proc.communicate()
    return proc.returncode, stdout or "", stderr or ""


def _audit_git_head(repo: Path) -> Optional[str]:
    rc, stdout, stderr = _audit_git_command(repo, ["rev-parse", "--verify", "HEAD"])
    if rc != 0:
        tail = (stderr or stdout or "").strip().splitlines()[-1:]
        detail = tail[0] if tail else f"git rev-parse rc={rc}"
        print(f"[audit] HEAD snapshot unavailable: {detail}", file=sys.stderr)
        return None
    return stdout.strip() or None


def _audit_snapshot(repo: Path, slug: str) -> tuple[dict[str, _AuditEntry], Optional[str]]:
    return _audit_snapshot_paths(repo, slug), _audit_git_head(repo)


def _iter_audit_paths(repo: Path, slug: str) -> Iterable[Path]:
    """Files to guard. Shared code dirs (full scope) + per-slug paths.

    rev 5: `configs/` is NOT in the shared scope — other slugs may publish
    legitimately. Only `configs/<slug>.json` is guarded (per-slug scope).
    """
    shared_dirs = [
        "engine", "prompts", "scripts", "bot", "dashboard",
        "tests", "docs", "messages", "schemas",
    ]
    for d in shared_dirs:
        root = repo / d
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if p.is_file():
                yield p
    # per-slug — config + state + probe
    self_cfg = repo / "configs" / f"{slug}.json"
    if self_cfg.is_file():
        yield self_cfg
    poll_state = repo / "output" / "poll_state"
    if poll_state.is_dir():
        for p in poll_state.glob(f"{slug}.*"):
            if p.is_file():
                yield p
    probe = repo / "output" / "probe" / slug
    if probe.is_dir():
        for p in probe.rglob("*"):
            if p.is_file():
                yield p
    # repo root files
    for name in ("CLAUDE.md", "AGENTS.md", "CONTEXT.md", "pyproject.toml",
                 "config.toml", "requirements.txt", "requirements-dev.txt"):
        rp = repo / name
        if rp.is_file():
            yield rp


def _audit_relpath(repo: Path, path: Path) -> Optional[str]:
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return None


def _git_changed_between_heads(repo: Path, pre_head: str, post_head: str) -> set[str]:
    rc, stdout, stderr = _audit_git_command(
        repo, ["diff", "--name-only", f"{pre_head}..{post_head}"]
    )
    if rc != 0:
        tail = (stderr or stdout or "").strip().splitlines()[-1:]
        detail = tail[0] if tail else f"git diff rc={rc}"
        print(f"[audit] HEAD diff unavailable: {detail}", file=sys.stderr)
        return set()
    return {line.strip() for line in stdout.splitlines() if line.strip()}


def _git_worktree_matches_head(repo: Path, head: str, relpath: str) -> bool:
    rc, _, _ = _audit_git_command(
        repo, ["diff", "--quiet", head, "--", relpath], capture=False
    )
    return rc == 0


def _audit_change_is_head_advance(repo: Path, path: Path, *,
                                  post_head: str, head_changed_paths: set[str]) -> bool:
    rel = _audit_relpath(repo, path)
    if rel is None or rel not in head_changed_paths:
        return False
    return _git_worktree_matches_head(repo, post_head, rel)


def _audit_diff(before: dict[str, _AuditEntry], after: dict[str, _AuditEntry],
                *, self_slug: str, configs_root: Path,
                pre_head: Optional[str] = None,
                post_head: Optional[str] = None) -> list[str]:
    """Returns paths that changed = violations.

    Per-slug policy for `configs/`:
    - self-slug config: any change = violation (publish is parent's job, post-audit)
    - other-slug config:
        - DELETED → violation (kill few-shot examples / settled configs)
        - CONTENT CHANGED → violation (someone else's config shouldn't move)
        - NEW → allowed (parallel agent publishing its slug — rev 5)

    All other paths (shared dirs, poll_state, probe, root files): any change = violation.
    """
    out: list[str] = []
    keys = set(before) | set(after)
    self_cfg_name = f"{self_slug}.json"
    cfg_root_str = str(configs_root)
    repo = configs_root.parent
    head_changed_paths: set[str] = set()
    if pre_head and post_head and pre_head != post_head:
        head_changed_paths = _git_changed_between_heads(repo, pre_head, post_head)
    for k in keys:
        b, a = before.get(k), after.get(k)
        kp = Path(k)
        if _audit_path_is_ignored(kp):
            continue
        is_other_slug_cfg = (
            str(kp.parent) == cfg_root_str and kp.name != self_cfg_name
        )
        if b is None:
            # NEW
            if is_other_slug_cfg:
                continue  # parallel publish allowed
            if post_head and _audit_change_is_head_advance(
                repo, kp, post_head=post_head, head_changed_paths=head_changed_paths
            ):
                continue
            out.append(f"{k} (NEW)")
            continue
        if a is None:
            if post_head and _audit_change_is_head_advance(
                repo, kp, post_head=post_head, head_changed_paths=head_changed_paths
            ):
                continue
            out.append(f"{k} (DELETED)")
            continue
        if b.sha256 != a.sha256 or b.size != a.size:
            if post_head and _audit_change_is_head_advance(
                repo, kp, post_head=post_head, head_changed_paths=head_changed_paths
            ):
                continue
            out.append(f"{k} (CONTENT CHANGED)")
    return out


# --- per-slug lock (filesystem) ---------------------------------------------


@contextlib.contextmanager
def _per_slug_lock(repo: Path, slug: str, *, timeout: float = 600.0,
                   poll_interval: float = 0.5):
    """Filesystem lock for the entire agentic generate + audit + publish window.
    Linux: fcntl.flock. Windows: no-op (single-machine dev box assumption).
    """
    try:
        import fcntl  # type: ignore
    except ImportError:  # Windows
        yield
        return
    lock_dir = repo / "output"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f".register_agentic.{slug}.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"per-slug lock timeout ({timeout}s): {lock_path}")
                time.sleep(poll_interval)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass


# --- preflight ---------------------------------------------------------------


def _codex_preflight() -> str:
    """Returns the codex CLI version string. Raises LLMNetworkError on missing/broken CLI."""
    try:
        proc = subprocess.run(
            [_codex_bin(), "--version"],
            capture_output=True, text=True, encoding="utf-8", timeout=10.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        raise LLMNetworkError(f"codex --version preflight failed: {type(e).__name__}: {e}") from e
    except OSError as e:
        raise LLMNetworkError(f"codex --version OSError: {e}") from e
    if proc.returncode != 0:
        raise LLMNetworkError(f"codex --version rc={proc.returncode}: {proc.stderr[:300]}")
    return (proc.stdout or "").strip()


# --- examples picker ---------------------------------------------------------


def _score_example(cfg: dict, digest: dict) -> int:
    """recognizer (+10), eTLD+1 host (+5), strategy (+3), URL path shape (+2)."""
    score = 0
    cfg_recognizer = (cfg.get("recognizer") or "").strip()
    digest_recognizer = ((digest.get("recognizer_hint") or {}).get("name") or "").strip()
    if cfg_recognizer and cfg_recognizer == digest_recognizer:
        score += 10
    # eTLD+1 approximation: last two dotted segments. Cheap (no public_suffix lib needed).
    def _etld1(url: str) -> str:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
        parts = host.split(".")
        return ".".join(parts[-2:]) if len(parts) >= 2 else host
    cfg_etld = _etld1(cfg.get("site") or cfg.get("url") or "")
    digest_etld = _etld1(digest.get("url") or "")
    if cfg_etld and cfg_etld == digest_etld:
        score += 5
    cfg_strategy = (cfg.get("strategy") or "").strip()
    digest_strategy = ((digest.get("strategy_hint") or {}).get("strategy") or "").strip()
    if cfg_strategy and digest_strategy and cfg_strategy == digest_strategy:
        score += 3
    return score


def _pick_examples(digest: dict, repo: Path, slug: str, *, n: int = 4) -> list[Path]:
    """Successful configs ranked by relevance score. Excludes current slug."""
    cfg_dir = repo / "configs"
    if not cfg_dir.is_dir():
        return []
    scored: list[tuple[int, Path]] = []
    self_path = cfg_dir / f"{slug}.json"
    for p in cfg_dir.glob("*.json"):
        if p == self_path:
            continue
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(cfg, dict):
            continue
        s = _score_example(cfg, digest)
        if s > 0:
            scored.append((s, p))
    scored.sort(key=lambda t: (-t[0], t[1].name))
    return [p for _, p in scored[:n]]


# --- tmpdir setup ------------------------------------------------------------


def _compress_digest_html(digest: dict, *, max_html_chars: int = 60_000) -> dict:
    """Trim raw HTML samples in `list_html` and `article_sample.html` to keep
    agent input under control. Same compression api_loop's prompt builder applies.
    Returns a shallow-copied dict with the HTML fields swapped (non-destructive).
    Without this, list_html + article_sample = ~80KB raw each ~20K tokens per read.
    """
    if _compress_html is None:
        return digest
    out = dict(digest)
    lh = out.get("list_html")
    if isinstance(lh, dict) and isinstance(lh.get("html"), str):
        lh2 = dict(lh)
        lh2["html"] = _compress_html(lh["html"])[:max_html_chars]
        lh2["prompt_compressed"] = True
        out["list_html"] = lh2
    asmp = out.get("article_sample")
    if isinstance(asmp, dict) and isinstance(asmp.get("html"), str):
        asmp2 = dict(asmp)
        asmp2["html"] = _compress_html(asmp["html"])[:max_html_chars]
        asmp2["prompt_compressed"] = True
        out["article_sample"] = asmp2
    return out


def _setup_workdir(digest: dict, slug: str, url: str, repo: Path,
                   failure_packet: Optional[dict] = None) -> Path:
    """Create tmpdir (outside repo) with AGENTS.md, digest.json, examples, validate wrapper."""
    workdir = Path(tempfile.mkdtemp(prefix=f"reg_agent_{slug}_"))
    # AGENTS.md (focused, agent-specific)
    if PROMPT_AGENTS_PATH.is_file():
        shutil.copy2(PROMPT_AGENTS_PATH, workdir / "AGENTS.md")
    # Inputs — digest compressed (raw HTML samples trimmed to 60K chars each).
    digest_for_agent = _compress_digest_html(digest, max_html_chars=60_000)
    (workdir / "digest.json").write_text(
        json.dumps(digest_for_agent, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Full digest for validate_config.py only. The child prompt points at the
    # compressed digest.json; the validator needs uncompressed HTML so grounding
    # failures are evidence, not prompt-compression artifacts.
    (workdir / "validator_digest.json").write_text(
        json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (workdir / "slug.txt").write_text(slug + "\n", encoding="utf-8")
    (workdir / "url.txt").write_text(url + "\n", encoding="utf-8")
    if failure_packet:
        (workdir / "failure_packet.json").write_text(
            json.dumps(failure_packet, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    # Examples — copy + manifest
    examples_dir = workdir / "examples"
    examples_dir.mkdir(parents=True, exist_ok=True)
    picked = _pick_examples(digest, repo, slug, n=2)
    manifest = []
    for p in picked:
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(cfg, dict):
            continue
        shutil.copy2(p, examples_dir / p.name)
        manifest.append({
            "slug": p.stem,
            "score": _score_example(cfg, digest),
            "reason": _example_reason(cfg, digest),
        })
    (examples_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # config_writer rules — pre-staged so agent doesn't need to read prompts/ from repo.
    # ~25KB / ~6K tokens. Agent reads this only if uncertain about a field.
    config_writer_src = REPO_ROOT / "prompts" / "config_writer.system.txt"
    if config_writer_src.is_file():
        shutil.copy2(config_writer_src, workdir / "config_writer_rules.txt")
    # validate wrapper — agent runs it. Copy so agent doesn't need to touch repo.
    if VALIDATE_WRAPPER_PATH.is_file():
        shutil.copy2(VALIDATE_WRAPPER_PATH, workdir / "validate_config.py")
    (workdir / "validator_attempt_log.py").write_text(
        VALIDATOR_ATTEMPT_LOGGER, encoding="utf-8"
    )
    py = sys.executable
    (workdir / "python_path.txt").write_text(py + "\n", encoding="utf-8")
    if sys.platform == "win32":
        (workdir / "run_validator.bat").write_text(
            "@echo off\r\n"
            "setlocal\r\n"
            "set \"VALIDATE_TIMING_DIR=%~dp0validate_timing\"\r\n"
            "set \"VALIDATOR_ATTEMPT_LOG=%VALIDATE_TIMING_DIR%\\agentic_attempt__candidate__%RANDOM%_%RANDOM%.json\"\r\n"
            f"\"{py}\" \"%~dp0validator_attempt_log.py\" start-path \"%VALIDATOR_ATTEMPT_LOG%\" %* >NUL 2>NUL\r\n"
            f"\"{py}\" \"%~dp0validate_config.py\" %*\r\n"
            "set \"VALIDATOR_RC=%ERRORLEVEL%\"\r\n"
            f"if defined VALIDATOR_ATTEMPT_LOG \"{py}\" \"%~dp0validator_attempt_log.py\" end \"%VALIDATOR_ATTEMPT_LOG%\" %VALIDATOR_RC% >NUL 2>NUL\r\n"
            "exit /b %VALIDATOR_RC%\r\n",
            encoding="utf-8",
        )
    else:
        sh_path = workdir / "run_validator.sh"
        sh_path.write_text(
            '#!/bin/sh\n'
            'export VALIDATE_TIMING_DIR="$(dirname "$0")/validate_timing"\n'
            f'VALIDATOR_ATTEMPT_LOG=$("{py}" "$(dirname "$0")/validator_attempt_log.py" start "$@")\n'
            f'"{py}" "$(dirname "$0")/validate_config.py" "$@"\n'
            'VALIDATOR_RC=$?\n'
            f'if [ -n "$VALIDATOR_ATTEMPT_LOG" ]; then "{py}" "$(dirname "$0")/validator_attempt_log.py" end "$VALIDATOR_ATTEMPT_LOG" "$VALIDATOR_RC" >/dev/null 2>&1; fi\n'
            'exit "$VALIDATOR_RC"\n',
            encoding="utf-8",
        )
        sh_path.chmod(0o755)
    return workdir


def _copy_timing_artifacts(workdir: Path, repo: Path) -> None:
    if os.environ.get("VALIDATE_TIMING", "").strip().lower() not in ("1", "true", "yes", "on"):
        return
    src = workdir / "validate_timing"
    if not src.is_dir():
        return
    dst = repo / "output" / "validate_timing"
    try:
        dst.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    for p in src.glob("*.json"):
        try:
            shutil.copy2(p, dst / p.name)
        except OSError:
            pass


def _agentic_timing_enabled() -> bool:
    return os.environ.get("VALIDATE_TIMING", "").strip().lower() in ("1", "true", "yes", "on")


def _preserve_agentic_workdir_enabled() -> bool:
    return os.environ.get("VALIDATE_TIMING_PRESERVE_WORKDIR", "").strip().lower() in (
        "1", "true", "yes", "on"
    )


def _safe_log_slug(slug: str) -> str:
    safe = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in slug)
    return safe[:120] or "unknown"


def _agentic_run_log_path(repo: Path, slug: str) -> Path:
    ts = time.strftime("%Y%m%dT%H%M%S", time.localtime())
    suffix = secrets.token_hex(3)
    return repo / "output" / "validate_timing" / f"agentic_run__{_safe_log_slug(slug)}__{ts}__pid{os.getpid()}__{suffix}.json"


def _read_json_optional(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_text_optional(path: Path, *, max_chars: int = 300_000) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n...[truncated {len(text) - max_chars} chars]"


def _workdir_file_listing(workdir: Path) -> list[dict]:
    out: list[dict] = []
    try:
        files = sorted(p for p in workdir.rglob("*") if p.is_file())
    except OSError:
        return out
    for p in files:
        try:
            st = p.stat()
        except OSError:
            continue
        out.append({
            "path": str(p.relative_to(workdir)),
            "size": st.st_size,
            "mtime": st.st_mtime,
        })
    return out


def _update_agentic_run_log(path: Path | None, event: str, **fields) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = _read_json_optional(path)
        if not isinstance(payload, dict):
            payload = {}
        events = payload.get("events")
        if not isinstance(events, list):
            events = []
        events.append({"event": event, "wall_time": time.time()})
        payload["events"] = events
        payload.update(fields)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def _copy_agentic_workdir_snapshot(workdir: Path, repo: Path, slug: str) -> Path | None:
    if not _preserve_agentic_workdir_enabled():
        return None
    dst_root = repo / "output" / "validate_timing" / "agentic_workdirs"
    ts = time.strftime("%Y%m%dT%H%M%S", time.localtime())
    dst = dst_root / f"{_safe_log_slug(slug)}__{ts}__pid{os.getpid()}__{secrets.token_hex(3)}"
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(workdir, dst, symlinks=True, dirs_exist_ok=False)
    except OSError:
        return None
    return dst


def _example_reason(cfg: dict, digest: dict) -> str:
    parts = []
    cfg_recognizer = (cfg.get("recognizer") or "").strip()
    digest_recognizer = ((digest.get("recognizer_hint") or {}).get("name") or "").strip()
    if cfg_recognizer and cfg_recognizer == digest_recognizer:
        parts.append(f"recognizer={cfg_recognizer}")
    cfg_strategy = (cfg.get("strategy") or "").strip()
    digest_strategy = ((digest.get("strategy_hint") or {}).get("strategy") or "").strip()
    if cfg_strategy and digest_strategy and cfg_strategy == digest_strategy:
        parts.append(f"strategy={cfg_strategy}")
    return ", ".join(parts) or "host/path heuristic"


def _build_user_prompt(slug: str, url: str, repo: Path) -> str:
    if PROMPT_USER_PATH.is_file():
        tpl = PROMPT_USER_PATH.read_text(encoding="utf-8")
    else:
        tpl = "TASK: register slug={{slug}} url={{url}}\nBegin."
    return (tpl.replace("{{ slug }}", slug)
              .replace("{{ url }}", url))


def _read_candidate_config(workdir: Path, candidate_path: object = None) -> dict:
    """Read the agent-written candidate from the tmpdir.

    The final Codex message is intentionally small and may only reference this
    file. Keep the accepted path shape narrow because the agent is untrusted.
    """
    raw = "./candidate.json" if candidate_path is None else str(candidate_path).strip()
    normalized = raw.replace("\\", "/")
    if normalized not in ("candidate.json", "./candidate.json"):
        raise LLMParseError(f"codex_agentic: unsupported candidate_path {raw!r}")
    p = workdir / "candidate.json"
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except OSError as e:
        raise LLMParseError(f"codex_agentic: cannot read ./candidate.json: {e}") from e
    except json.JSONDecodeError as e:
        raise LLMParseError(f"codex_agentic: ./candidate.json is not JSON: {e}") from e
    if not isinstance(cfg, dict):
        raise LLMParseError(
            f"codex_agentic: ./candidate.json is not a JSON object: {type(cfg).__name__}"
        )
    return cfg


# --- subprocess + process tree kill ------------------------------------------


def _kill_process_tree(pid: int) -> None:
    """Cross-platform process tree kill. Windows: taskkill /T /F. Linux: SIGKILL group."""
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                capture_output=True, text=True, timeout=10.0,
            )
        except (subprocess.TimeoutExpired, OSError):
            pass
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        # fallback: per-pid
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def _codex_classify_error(stderr_text: str, stdout_text: str, rc: int) -> LLMError:
    if "stdin is closed for this session" in stderr_text:
        return LLMNetworkError(
            f"codex_agentic_transient_session_stdin_closed (rc={rc}, "
            f"stderr tail: {stderr_text[-300:]!r})"
        )
    return _codex_base_classify_error(stderr_text, stdout_text, rc)


def _codex_timeout_prefix(stderr_text: str) -> str:
    marker = "Reading prompt from stdin"
    stderr_substantive = stderr_text.strip()
    if marker in stderr_substantive:
        tail = stderr_substantive.split(marker, 1)[-1].strip()
        if len(tail) < 200:
            return "codex_agentic_transient_timeout"
    return "codex_agentic timeout"


def _sandbox_args(workdir: Path) -> list[str]:
    """Codex exec sandbox flags for the register agent.

    The validator must make real network requests from inside the agent loop.
    N100 measurement showed Linux workspace-write breaks that path with DNS
    failures, so the trust boundary is prompt + AGENTS + post-run audit +
    parent re-validation, as accepted in ADR 0020.
    """
    return ["--dangerously-bypass-approvals-and-sandbox"]


# --- codex usage extraction (multi-turn SUM) ---------------------------------


def _sum_usage(stdout: str) -> tuple[int, int]:
    """Sum input_tokens + output_tokens across ALL `turn.completed.usage` events.
    Multi-turn codex agentic — each turn has its own usage. codex.py reads only
    the last; here we accumulate for accurate token cost reporting."""
    total_in = 0
    total_out = 0
    for line in stdout.splitlines():
        s = line.strip()
        if not s or not s.startswith("{"):
            continue
        try:
            ev = json.loads(s)
        except json.JSONDecodeError:
            continue
        if ev.get("type") != "turn.completed":
            continue
        usage = ev.get("usage") or {}
        try:
            total_in += int(usage.get("input_tokens") or 0)
            total_out += int(usage.get("output_tokens") or 0)
        except (TypeError, ValueError):
            pass
    return total_in, total_out


# --- main entry --------------------------------------------------------------


@dataclass
class AgenticResult:
    """Result of one agentic generate run.

    Caller uses `config` (in-memory dict) to atomically publish to
    `repo/configs/<slug>.json` via `tempfile.NamedTemporaryFile(dir=...)` +
    `Path.replace`. The `workdir` is cleaned up automatically unless
    `keep_workdir=True` or env `KEEP_AGENT_WORKDIR` is set.
    """
    config: dict
    report: ValidationReport
    workdir: Path
    attempts: list[dict]
    stop_reason: str
    codex_version: str
    prompt_tokens: int
    completion_tokens: int
    wall_s: float


async def _run_codex_agentic_once(
    *,
    digest: dict,
    slug: str,
    url: str,
    repo: Path,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    max_cycles: int = DEFAULT_MAX_CYCLES,
    model: str = "gpt-5.4-mini",
    reasoning_effort: str = "low",
    keep_workdir: bool = False,
    failure_packet: Optional[dict] = None,
) -> AgenticResult:
    """End-to-end agentic generate.

    1. preflight codex --version
    2. acquire per-slug lock
    3. setup tmpdir (AGENTS.md, digest, examples, validate wrapper)
    4. pre-audit snapshot
    5. codex exec (bypass sandbox, timeout, process tree kill)
    6. post-audit — any change outside tmpdir → AuditFailError
    7. parse agent output JSON
    8. parent re-validate (validate_built_config)
    9. return AgenticResult — caller publishes from candidate_path
    """
    version = _codex_preflight()
    workdir = _setup_workdir(digest, slug, url, repo, failure_packet=failure_packet)
    run_log_path = _agentic_run_log_path(repo, slug) if _agentic_timing_enabled() else None
    _update_agentic_run_log(
        run_log_path,
        "workdir_created",
        slug=slug,
        url=url,
        workdir=str(workdir),
        preserve_workdir=_preserve_agentic_workdir_enabled(),
        digest_path=str(workdir / "digest.json"),
        failure_packet_path=str(workdir / "failure_packet.json") if failure_packet else None,
        digest=_read_json_optional(workdir / "digest.json"),
        failure_packet=_read_json_optional(workdir / "failure_packet.json"),
    )
    pre, pre_head = _audit_snapshot(repo, slug)
    t0 = time.time()
    stdout_text = ""
    stderr_text = ""
    rc = -999
    try:
        with _per_slug_lock(repo, slug):
            out_file = workdir / "last.json"
            user_prompt = _build_user_prompt(slug, url, repo)
            if run_log_path is not None:
                (workdir / "codex_user_prompt.txt").write_text(user_prompt, encoding="utf-8")
            args = [
                _codex_bin(), "exec",
                "-C", str(workdir),
                "--skip-git-repo-check",
                "--ephemeral",
                "--ignore-user-config",
                "--color", "never",
                "--json",
                "-c", f"model={model}",
                "-c", f"model_reasoning_effort={reasoning_effort}",
                "--output-last-message", str(out_file),
            ]
            args.extend(_sandbox_args(workdir))
            # NOTE: --output-schema dropped — OpenAI structured output requires
            # additionalProperties:false on all nested objects, but `config` has
            # arbitrary user-defined keys. Schema kept as prompt context only.
            # Linux: new session so the whole process group can be killed on timeout.
            preexec = os.setsid if sys.platform != "win32" else None
            # Windows: CREATE_NEW_PROCESS_GROUP so taskkill /T can find tree.
            creationflags = 0
            if sys.platform == "win32":
                creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            child_env = os.environ.copy()
            child_env["REPO_ROOT"] = str(repo)  # validate wrapper uses this
            child_env["VALIDATE_TIMING_DIR"] = str(workdir / "validate_timing")
            venv_bin = Path(sys.executable).parent
            child_env["PATH"] = str(venv_bin) + os.pathsep + child_env.get("PATH", "")
            _update_agentic_run_log(
                run_log_path,
                "codex_start",
                codex_version=version,
                codex_args=args,
                child_env={
                    "REPO_ROOT": child_env.get("REPO_ROOT"),
                    "VALIDATE_TIMING": child_env.get("VALIDATE_TIMING"),
                    "VALIDATE_TIMING_DIR": child_env.get("VALIDATE_TIMING_DIR"),
                    "VALIDATE_TIMING_PRESERVE_WORKDIR": child_env.get("VALIDATE_TIMING_PRESERVE_WORKDIR"),
                    "PATH_first": child_env.get("PATH", "").split(os.pathsep)[0],
                },
                user_prompt_path=str(workdir / "codex_user_prompt.txt") if run_log_path is not None else None,
                user_prompt=user_prompt,
            )
            proc = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=child_env,
                preexec_fn=preexec,
                creationflags=creationflags,
            )
            try:
                stdout_text, stderr_text = proc.communicate(input=user_prompt, timeout=timeout_s)
                rc = proc.returncode
            except subprocess.TimeoutExpired:
                _kill_process_tree(proc.pid)
                try:
                    stdout_text, stderr_text = proc.communicate(timeout=10.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    stdout_text, stderr_text = proc.communicate(timeout=5.0)
                prefix = _codex_timeout_prefix(stderr_text)
                raise LLMNetworkError(
                    f"{prefix} after {timeout_s}s "
                    f"(stderr tail: {stderr_text[-300:]!r})"
                )
            finally:
                if run_log_path is not None:
                    (workdir / "codex_stdout.jsonl").write_text(stdout_text, encoding="utf-8", errors="replace")
                    (workdir / "codex_stderr.txt").write_text(stderr_text, encoding="utf-8", errors="replace")
                    (workdir / "codex_run_meta.json").write_text(
                        json.dumps({
                            "rc": rc,
                            "timeout_s": timeout_s,
                            "wall_s": time.time() - t0,
                            "stdout_path": "codex_stdout.jsonl",
                            "stderr_path": "codex_stderr.txt",
                            "last_json_exists": (workdir / "last.json").exists(),
                            "candidate_json_exists": (workdir / "candidate.json").exists(),
                            "validate_timing_files": [
                                str(p.relative_to(workdir))
                                for p in sorted((workdir / "validate_timing").glob("*.json"))
                            ] if (workdir / "validate_timing").is_dir() else [],
                        }, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    _update_agentic_run_log(
                        run_log_path,
                        "codex_end",
                        rc=rc,
                        wall_s=time.time() - t0,
                        stdout_path=str(workdir / "codex_stdout.jsonl"),
                        stderr_path=str(workdir / "codex_stderr.txt"),
                        stdout_tail=stdout_text[-5000:],
                        stderr_tail=stderr_text[-5000:],
                        last_json=_read_json_optional(workdir / "last.json"),
                        candidate_json=_read_json_optional(workdir / "candidate.json"),
                        workdir_files=_workdir_file_listing(workdir),
                    )
            # post-audit — any change outside tmpdir = violation
            post, post_head = _audit_snapshot(repo, slug)
            violations = _audit_diff(pre, post,
                                     self_slug=slug,
                                     configs_root=repo / "configs",
                                     pre_head=pre_head,
                                     post_head=post_head)
            if violations:
                raise AuditFailError(
                    f"agent wrote outside its workdir ({len(violations)} files): "
                    f"{violations[:5]}",
                    violations=violations,
                )
        # outside lock — error classification + parse + parent re-validate.
        if rc != 0:
            raise _codex_classify_error(stderr_text, stdout_text, rc)
        last_text = ""
        last_msg_file = workdir / "last.json"
        if last_msg_file.exists():
            last_text = last_msg_file.read_text(encoding="utf-8").strip()
        if not last_text:
            raise LLMParseError(
                f"codex_agentic: empty agent output (stderr tail: {stderr_text[-300:]!r})"
            )
        # Tolerant parse — agent may add prose around the JSON since --output-schema
        # is no longer enforcing strict structure. Extract first {...} block.
        # On parse failure: fall back to ./candidate.json that the agent writes
        # separately. The codex CLI truncates the final agent message (openai/codex
        # issues #4138 / #15451 — no public knob to raise the cap; the truncation
        # happens silently when tools are active). The candidate file is written by
        # the agent before the final message, so it survives the truncation.
        parsed = None
        parse_error: Optional[str] = None
        try:
            parsed = json.loads(last_text)
        except json.JSONDecodeError:
            i = last_text.find("{")
            j = last_text.rfind("}")
            if i >= 0 and j > i:
                try:
                    parsed = json.loads(last_text[i : j + 1])
                except json.JSONDecodeError as e:
                    parse_error = str(e)
            else:
                parse_error = "no balanced { } block"

        if parsed is None:
            recovered: Optional[dict] = None
            try:
                recovered = _read_candidate_config(workdir)
            except LLMParseError:
                recovered = None
            if isinstance(recovered, dict) and recovered:
                # Assume the agent intended ok=true with this candidate; parent
                # re-validation below is the real arbiter. If validate fails the
                # caller still sees a precise gen_fail, not LLMParseError.
                print(
                    f"[codex_agentic] last.json parse failed ({parse_error}) — "
                    f"recovered candidate.json ({(workdir / 'candidate.json').stat().st_size}B). "
                    f"Parent will re-validate.",
                    flush=True,
                )
                parsed = {
                    "ok": True,
                    "config": recovered,
                    "attempts": [],
                    "stop_reason": "last_message_truncated_recovered_from_candidate",
                }
            else:
                raise LLMParseError(
                    f"codex_agentic: agent output not JSON ({parse_error}) "
                    f"and ./candidate.json missing/empty — first 300 chars: "
                    f"{last_text[:300]!r}"
                )
        if not isinstance(parsed, dict):
            raise LLMParseError(f"codex_agentic: agent output not a JSON object: {type(parsed).__name__}")
        ok_flag = bool(parsed.get("ok"))
        config = parsed.get("config")
        attempts = parsed.get("attempts") or []
        stop_reason = str(parsed.get("stop_reason") or "")
        if ok_flag and (not isinstance(config, dict) or not config):
            config = _read_candidate_config(workdir, parsed.get("candidate_path"))

        # Compute usage once — reused for both success result and any failure-path
        # GenerationError so measurement scripts see the cost of failed runs too.
        prompt_tokens, completion_tokens = _sum_usage(stdout_text)

        def _gen_fail(msg: str, *, stop: str, **kw):
            return GenerationError(
                msg,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                wall_s=time.time() - t0,
                stop_reason=stop,
                codex_version=version,
                **kw,
            )

        if not ok_flag or not isinstance(config, dict):
            if not isinstance(config, dict) or not config:
                recovered_config: Optional[dict] = None
                try:
                    recovered_config = _read_candidate_config(workdir)
                except LLMParseError:
                    recovered_config = None
                if isinstance(recovered_config, dict) and recovered_config:
                    config = recovered_config
            raise _gen_fail(
                f"agent did not produce a passing config (stop_reason={stop_reason!r})",
                stop=stop_reason or "agent_gave_up",
                last_config=config if isinstance(config, dict) else None,
                last_feedback=json.dumps(attempts, ensure_ascii=False)[:1000],
            )
        # `headless: false` reject (codex review LOW). N100 production = headless only.
        if _has_headless_false(config):
            raise _gen_fail(
                "agent emitted `headless: false` — rejected (N100 = headless only)",
                stop="headless_false_rejected",
                last_config=config,
                last_feedback="headless:false not allowed",
            )
        # Parent re-validation — trust boundary anchor. Agent ok=true means nothing
        # until validate_built_config (fresh fetch) agrees.
        report = await validate_built_config(config, digest=digest, fetch_articles=1)
        if not report.ok:
            raise _gen_fail(
                f"parent re-validate failed after agent claimed ok "
                f"(stop_reason={stop_reason!r}): {report.feedback_text()[:500]}",
                stop="parent_revalidate_fail",
                last_config=config,
                last_feedback=report.feedback_text(),
            )
        return AgenticResult(
            config=config,
            report=report,
            workdir=workdir,
            attempts=attempts if isinstance(attempts, list) else [],
            stop_reason=stop_reason or "validate_pass",
            codex_version=version,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            wall_s=time.time() - t0,
        )
    finally:
        _copy_timing_artifacts(workdir, repo)
        snapshot_path = _copy_agentic_workdir_snapshot(workdir, repo, slug)
        _update_agentic_run_log(
            run_log_path,
            "cleanup",
            workdir_files=_workdir_file_listing(workdir),
            preserved_workdir=str(snapshot_path) if snapshot_path is not None else None,
        )
        if not keep_workdir and not os.environ.get("KEEP_AGENT_WORKDIR"):
            shutil.rmtree(workdir, ignore_errors=True)


def _is_retryable_codex_agentic_error(exc: LLMNetworkError) -> bool:
    msg = str(exc)
    return (
        "codex_agentic_transient_session_stdin_closed" in msg
        or "codex_agentic_transient_timeout" in msg
    )


async def run_codex_agentic(
    *,
    digest: dict,
    slug: str,
    url: str,
    repo: Path,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    max_cycles: int = DEFAULT_MAX_CYCLES,
    model: str = "gpt-5.4-mini",
    reasoning_effort: str = "low",
    keep_workdir: bool = False,
    failure_packet: Optional[dict] = None,
) -> AgenticResult:
    """Run codex agentic generation, retrying one known transient CLI/session fault."""
    try:
        return await _run_codex_agentic_once(
            digest=digest,
            slug=slug,
            url=url,
            repo=repo,
            timeout_s=timeout_s,
            max_cycles=max_cycles,
            model=model,
            reasoning_effort=reasoning_effort,
            keep_workdir=keep_workdir,
            failure_packet=failure_packet,
        )
    except LLMNetworkError as e:
        if not _is_retryable_codex_agentic_error(e):
            raise
        print(f"[codex_agentic] transient CLI fault; retrying once: {e}", flush=True)
    return await _run_codex_agentic_once(
        digest=digest,
        slug=slug,
        url=url,
        repo=repo,
        timeout_s=timeout_s,
        max_cycles=max_cycles,
        model=model,
        reasoning_effort=reasoning_effort,
        keep_workdir=keep_workdir,
        failure_packet=failure_packet,
    )


def _has_headless_false(cfg: dict) -> bool:
    """Recursively detect `"headless": false`. Reject path for N100 headless-only."""
    if not isinstance(cfg, dict):
        return False
    for k, v in cfg.items():
        if k == "headless" and v is False:
            return True
        if isinstance(v, dict) and _has_headless_false(v):
            return True
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict) and _has_headless_false(item):
                    return True
    return False


__all__ = [
    "run_codex_agentic",
    "AgenticResult",
    "GenerationError",
    "AuditFailError",
    "DEFAULT_TIMEOUT_S",
    "DEFAULT_MAX_CYCLES",
]
