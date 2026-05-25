"""Codex agentic mode for the `config_generate` call_site.

Replaces the 4-retry API loop (`generate_config_validated`) with a single
multi-turn codex agent session. The agent has read access to the entire repo
(prior-art lookup) and writes a *candidate* config to its tmpdir. The parent
process **re-validates** the candidate independently and atomically publishes
it to `configs/<slug>.json`.

Trust boundary (rev 4 — see `output/plan_register_agentic.md`):
- On Windows the codex sandbox blocks all `workspace-write` shell commands
  (empirically — see `scripts/experiments/codex_sandbox_probe.py`), so we
  use `--dangerously-bypass-approvals-and-sandbox` and rely on a SHA256+mtime
  audit to detect any out-of-bounds write.
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
    from generate.codex import _classify_error as _codex_classify_error, _codex_bin
except ImportError:  # codex.py not on path in some test setups
    from .codex import _classify_error as _codex_classify_error, _codex_bin  # type: ignore

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


def _audit_diff(before: dict[str, _AuditEntry], after: dict[str, _AuditEntry],
                *, self_slug: str, configs_root: Path) -> list[str]:
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
    for k in keys:
        b, a = before.get(k), after.get(k)
        kp = Path(k)
        is_other_slug_cfg = (
            str(kp.parent) == cfg_root_str and kp.name != self_cfg_name
        )
        if b is None:
            # NEW
            if is_other_slug_cfg:
                continue  # parallel publish allowed
            out.append(f"{k} (NEW)")
            continue
        if a is None:
            out.append(f"{k} (DELETED)")
            continue
        if b.sha256 != a.sha256 or b.size != a.size:
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
        out["list_html"] = lh2
    asmp = out.get("article_sample")
    if isinstance(asmp, dict) and isinstance(asmp.get("html"), str):
        asmp2 = dict(asmp)
        asmp2["html"] = _compress_html(asmp["html"])[:max_html_chars]
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
    py = sys.executable
    (workdir / "python_path.txt").write_text(py + "\n", encoding="utf-8")
    if sys.platform == "win32":
        (workdir / "run_validator.bat").write_text(
            f'@echo off\r\n"{py}" "%~dp0validate_config.py" %*\r\n',
            encoding="utf-8",
        )
    else:
        sh_path = workdir / "run_validator.sh"
        sh_path.write_text(
            f'#!/bin/sh\nexec "{py}" "$(dirname "$0")/validate_config.py" "$@"\n',
            encoding="utf-8",
        )
        sh_path.chmod(0o755)
    return workdir


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
    pre = _audit_snapshot_paths(repo, slug)
    t0 = time.time()
    stdout_text = ""
    stderr_text = ""
    rc = -999
    try:
        with _per_slug_lock(repo, slug):
            out_file = workdir / "last.json"
            user_prompt = _build_user_prompt(slug, url, repo)
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
                "--dangerously-bypass-approvals-and-sandbox",
            ]
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
            venv_bin = Path(sys.executable).parent
            child_env["PATH"] = str(venv_bin) + os.pathsep + child_env.get("PATH", "")
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
                raise LLMNetworkError(
                    f"codex_agentic timeout after {timeout_s}s "
                    f"(stderr tail: {stderr_text[-300:]!r})"
                )
            # post-audit — any change outside tmpdir = violation
            post = _audit_snapshot_paths(repo, slug)
            violations = _audit_diff(pre, post,
                                     self_slug=slug,
                                     configs_root=repo / "configs")
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
        try:
            parsed = json.loads(last_text)
        except json.JSONDecodeError:
            i = last_text.find("{")
            j = last_text.rfind("}")
            if i < 0 or j <= i:
                raise LLMParseError(
                    f"codex_agentic: agent output not JSON: first 300 chars: {last_text[:300]!r}"
                )
            try:
                parsed = json.loads(last_text[i : j + 1])
            except json.JSONDecodeError as e:
                raise LLMParseError(
                    f"codex_agentic: agent output not JSON after block extract: {e} "
                    f"— first 300 chars: {last_text[:300]!r}"
                )
        if not isinstance(parsed, dict):
            raise LLMParseError(f"codex_agentic: agent output not a JSON object: {type(parsed).__name__}")
        ok_flag = bool(parsed.get("ok"))
        config = parsed.get("config")
        attempts = parsed.get("attempts") or []
        stop_reason = str(parsed.get("stop_reason") or "")

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
        if not keep_workdir and not os.environ.get("KEEP_AGENT_WORKDIR"):
            shutil.rmtree(workdir, ignore_errors=True)


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
