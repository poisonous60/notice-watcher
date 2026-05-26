"""codex_agentic 모듈 단위 테스트.

subprocess 직접 호출 안 함 — Popen + _codex_preflight 를 mock 으로 가로채서 결정성 확보.
실제 codex CLI 가 시스템에 없어도 통과해야 함.

검증 케이스:
- audit snapshot diff — content change 감지
- audit snapshot diff — mtime spoof (같은 size, 다른 content) 감지 via SHA
- audit snapshot diff — NEW file 감지
- _has_headless_false — nested headless:false 검출
- _pick_examples — recognizer 일치 high score
- _setup_workdir — AGENTS.md / digest.json / examples / validate wrapper 박힘
- AUDIT_FAIL raised on out-of-tmpdir write (mocked codex)
- timeout → LLMNetworkError
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from generate import codex_agentic as ca  # noqa: E402
from generate.llm_base import LLMNetworkError  # noqa: E402
import scripts.validate_config as validate_config_cli  # noqa: E402


REPO = Path(__file__).resolve().parent.parent.parent


def _check(name: str, ok: bool, detail: str) -> tuple[str, bool, str]:
    return (name, ok, detail)


def _make_tmp_repo() -> Path:
    """audit 테스트용 fake repo 디렉토리. configs/, engine/, scripts/ 빈 sub-dir 만."""
    d = Path(tempfile.mkdtemp(prefix="ca_test_repo_"))
    for sub in ("configs", "engine", "scripts", "prompts", "output/poll_state",
                "output/probe"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


def run() -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []

    # ----- 1. _has_headless_false: nested 검출 -----
    cases.append(_check(
        "headless_false_nested",
        ca._has_headless_false({"strategy": "playwright_html",
                                "playwright": {"headless": False}}),
        "should detect nested",
    ))
    cases.append(_check(
        "headless_false_in_list",
        ca._has_headless_false({"items": [{"headless": False}]}),
        "should detect in list",
    ))
    cases.append(_check(
        "headless_true_no_detect",
        not ca._has_headless_false({"playwright": {"headless": True}}),
        "should not detect headless:true",
    ))
    cases.append(_check(
        "headless_missing_no_detect",
        not ca._has_headless_false({"strategy": "httpx_html"}),
        "should not detect when key missing",
    ))

    # ----- 1b. Codex child sandbox flags: networked agentic path. -----
    with mock.patch.object(ca.sys, "platform", "linux"):
        linux_workdir = Path("/tmp/reg_agent_test")
        linux_args = ca._sandbox_args(linux_workdir)
    cases.append(_check(
        "sandbox_args_linux_bypass_for_networked_validator",
        linux_args == ["--dangerously-bypass-approvals-and-sandbox"],
        f"got {linux_args!r}",
    ))
    with mock.patch.object(ca.sys, "platform", "win32"):
        win_args = ca._sandbox_args(Path("C:/Temp/reg_agent_test"))
    cases.append(_check(
        "sandbox_args_windows_bypass",
        win_args == ["--dangerously-bypass-approvals-and-sandbox"],
        f"got {win_args!r}",
    ))

    # ----- 2. _score_example -----
    digest = {
        "url": "https://example.com/board",
        "recognizer_hint": {"name": "myrec"},
        "strategy_hint": {"strategy": "httpx_html"},
    }
    high_cfg = {"recognizer": "myrec", "site": "https://example.com/x",
                "strategy": "httpx_html"}
    low_cfg = {"recognizer": "other", "site": "https://other.com/x",
               "strategy": "playwright_html"}
    cases.append(_check(
        "score_recognizer_host_strategy_combo",
        ca._score_example(high_cfg, digest) >= 10 + 5 + 3,
        f"got score={ca._score_example(high_cfg, digest)}",
    ))
    cases.append(_check(
        "score_no_match_zero",
        ca._score_example(low_cfg, digest) == 0,
        f"got score={ca._score_example(low_cfg, digest)}",
    ))

    # ----- 3. _audit_snapshot_paths + _audit_diff: content change detect -----
    fake_repo = _make_tmp_repo()
    try:
        # seed: 공유 코드 파일 1개
        (fake_repo / "engine" / "a.py").write_text("ORIGINAL", encoding="utf-8")
        slug = "testsite"
        cfg_root = fake_repo / "configs"
        pre = ca._audit_snapshot_paths(fake_repo, slug)
        # mutate
        (fake_repo / "engine" / "a.py").write_text("MUTATED", encoding="utf-8")
        post = ca._audit_snapshot_paths(fake_repo, slug)
        diff = ca._audit_diff(pre, post, self_slug=slug, configs_root=cfg_root)
        cases.append(_check(
            "audit_detects_content_change",
            any("a.py" in d for d in diff),
            f"diff={diff}",
        ))

        # ----- 4. mtime spoof — 같은 size 다른 content. utime 으로 mtime 복원. SHA 가 잡아야. -----
        (fake_repo / "engine" / "a.py").write_text("ORIGINAL", encoding="utf-8")
        pre2 = ca._audit_snapshot_paths(fake_repo, slug)
        orig_mtime_ns = (fake_repo / "engine" / "a.py").stat().st_mtime_ns
        # write same-length content, then restore mtime
        time.sleep(0.01)  # ensure mtime would naturally change
        (fake_repo / "engine" / "a.py").write_text("MUTATEDX", encoding="utf-8")
        os.utime(fake_repo / "engine" / "a.py",
                 ns=(orig_mtime_ns, orig_mtime_ns))
        post2 = ca._audit_snapshot_paths(fake_repo, slug)
        diff2 = ca._audit_diff(pre2, post2, self_slug=slug, configs_root=cfg_root)
        cases.append(_check(
            "audit_catches_mtime_spoof_via_sha",
            any("a.py" in d for d in diff2),
            f"diff={diff2} — SHA should catch same-len different-content",
        ))

        # ----- 5. NEW file detection (shared dir) -----
        (fake_repo / "engine" / "b.py").write_text("INTRUDER", encoding="utf-8")
        post3 = ca._audit_snapshot_paths(fake_repo, slug)
        diff3 = ca._audit_diff(pre, post3, self_slug=slug, configs_root=cfg_root)
        cases.append(_check(
            "audit_detects_new_file",
            any("b.py" in d and "NEW" in d for d in diff3),
            f"diff={diff3}",
        ))

        # ----- 6a. other-slug config NEW = allowed (parallel publish, rev 5) -----
        pre4 = ca._audit_snapshot_paths(fake_repo, slug)
        (fake_repo / "configs" / "OTHER.json").write_text(json.dumps({"k": 1}),
                                                         encoding="utf-8")
        post4 = ca._audit_snapshot_paths(fake_repo, slug)
        diff4 = ca._audit_diff(pre4, post4, self_slug=slug, configs_root=cfg_root)
        cases.append(_check(
            "audit_allows_other_slug_new_publish",
            not any("OTHER.json" in d for d in diff4),
            f"diff={diff4} (NEW other-slug config should be allowed)",
        ))

        # ----- 6b. other-slug config CONTENT CHANGED = VIOLATION (audit hole fix) -----
        pre4b = ca._audit_snapshot_paths(fake_repo, slug)
        (fake_repo / "configs" / "OTHER.json").write_text(json.dumps({"k": 2}),
                                                         encoding="utf-8")
        post4b = ca._audit_snapshot_paths(fake_repo, slug)
        diff4b = ca._audit_diff(pre4b, post4b, self_slug=slug, configs_root=cfg_root)
        cases.append(_check(
            "audit_catches_other_slug_content_change",
            any("OTHER.json" in d and "CONTENT" in d for d in diff4b),
            f"diff={diff4b} (other slug's config shouldn't move)",
        ))

        # ----- 6c. other-slug config DELETED = VIOLATION (the actual bug — agent ate few-shot example) -----
        pre4c = ca._audit_snapshot_paths(fake_repo, slug)
        (fake_repo / "configs" / "OTHER.json").unlink()
        post4c = ca._audit_snapshot_paths(fake_repo, slug)
        diff4c = ca._audit_diff(pre4c, post4c, self_slug=slug, configs_root=cfg_root)
        cases.append(_check(
            "audit_catches_other_slug_delete",
            any("OTHER.json" in d and "DELETED" in d for d in diff4c),
            f"diff={diff4c} (DELETE of other-slug config = the few-shot-eat bug)",
        ))

        # ----- 7. self slug config 변경은 audit 잡음 -----
        (fake_repo / "configs" / f"{slug}.json").write_text(json.dumps({"k": 1}),
                                                            encoding="utf-8")
        pre5 = ca._audit_snapshot_paths(fake_repo, slug)
        (fake_repo / "configs" / f"{slug}.json").write_text(json.dumps({"k": 2}),
                                                            encoding="utf-8")
        post5 = ca._audit_snapshot_paths(fake_repo, slug)
        diff5 = ca._audit_diff(pre5, post5, self_slug=slug, configs_root=cfg_root)
        cases.append(_check(
            "audit_catches_self_slug_config_change",
            any(f"{slug}.json" in d for d in diff5),
            f"diff={diff5} (agent shouldn't touch its own slug config)",
        ))

        # ----- 7b. Python bytecode/cache rewrites are runtime noise, not agent writes. -----
        pycache = fake_repo / "scripts" / "__pycache__"
        pycache.mkdir(parents=True, exist_ok=True)
        pyc = pycache / "register.cpython-313.pyc"
        real_script = fake_repo / "scripts" / "real_violation.py"
        pyc.write_bytes(b"old-bytecode")
        real_script.write_text("old", encoding="utf-8")
        pre_cache = ca._audit_snapshot_paths(fake_repo, slug)
        pyc.write_bytes(b"new-bytecode")
        real_script.write_text("new", encoding="utf-8")
        post_cache = ca._audit_snapshot_paths(fake_repo, slug)
        diff_cache = ca._audit_diff(pre_cache, post_cache, self_slug=slug, configs_root=cfg_root)
        cases.append(_check(
            "audit_ignores_python_bytecode_but_keeps_real_violations",
            (not any("__pycache__" in d or d.endswith(".pyc (CONTENT CHANGED)") for d in diff_cache)
             and any("real_violation.py" in d and "CONTENT" in d for d in diff_cache)),
            f"diff={diff_cache}",
        ))
    finally:
        shutil.rmtree(fake_repo, ignore_errors=True)

    # ----- 8. _setup_workdir: 박는 파일들 확인 -----
    fake_repo2 = _make_tmp_repo()
    try:
        # seed examples 후보
        (fake_repo2 / "configs" / "ex1.json").write_text(
            json.dumps({"site": "https://example.com/", "recognizer": "myrec",
                        "strategy": "httpx_html"}), encoding="utf-8")
        # PROMPT_AGENTS_PATH + VALIDATE_WRAPPER_PATH 가 실제 repo 의 파일이므로 임시 stub.
        wd = None
        try:
            failure_packet = {
                "source": "api_loop_once",
                "candidate_config": {"strategy": "httpx_html"},
                "validation_feedback": "[FAIL] posts_nonempty",
            }
            wd = ca._setup_workdir(
                {"recognizer_hint": {"name": "myrec"},
                 "strategy_hint": {"strategy": "httpx_html"},
                 "url": "https://example.com/board"},
                "testslug",
                "https://example.com/board",
                fake_repo2,
                failure_packet=failure_packet,
            )
            files_present = {
                "digest.json": (wd / "digest.json").exists(),
                "slug.txt": (wd / "slug.txt").exists(),
                "url.txt": (wd / "url.txt").exists(),
                "repo_path_absent": not (wd / "repo_path.txt").exists(),
                "python_path": (wd / "python_path.txt").exists(),
                "attempt_logger": (wd / "validator_attempt_log.py").exists(),
                "examples_dir": (wd / "examples").exists(),
                "manifest": (wd / "examples" / "manifest.json").exists(),
                "failure_packet": (wd / "failure_packet.json").exists(),
            }
            cases.append(_check(
                "workdir_files_present",
                all(files_present.values()),
                f"present={files_present}",
            ))
            slug_content = (wd / "slug.txt").read_text(encoding="utf-8").strip()
            cases.append(_check(
                "workdir_slug_content",
                slug_content == "testslug",
                f"got slug={slug_content!r}",
            ))
            python_path_content = (wd / "python_path.txt").read_text(encoding="utf-8").strip()
            cases.append(_check(
                "workdir_python_path_content",
                python_path_content == sys.executable,
                f"got python_path={python_path_content!r}, expected={sys.executable!r}",
            ))
            got_packet = json.loads((wd / "failure_packet.json").read_text(encoding="utf-8"))
            cases.append(_check(
                "workdir_failure_packet_content",
                got_packet == failure_packet,
                f"got packet={got_packet!r}",
            ))
            launcher_name = "run_validator.bat" if sys.platform == "win32" else "run_validator.sh"
            launcher = wd / launcher_name
            launcher_text = launcher.read_text(encoding="utf-8") if launcher.exists() else ""
            cases.append(_check(
                "workdir_validator_launcher_present",
                launcher.exists(),
                f"expected {launcher_name} in workdir",
            ))
            cases.append(_check(
                "workdir_validator_launcher_uses_sys_executable",
                (sys.executable in launcher_text
                 and "validate_config.py" in launcher_text
                 and "validator_attempt_log.py" in launcher_text),
                f"launcher={launcher_text!r}",
            ))
            if sys.platform != "win32":
                cases.append(_check(
                    "workdir_validator_launcher_executable",
                    os.access(launcher, os.X_OK),
                    f"mode={oct(launcher.stat().st_mode) if launcher.exists() else 'missing'}",
                ))
            candidate = wd / "candidate.json"
            candidate.write_text(json.dumps({"site": "https://example.com/"}), encoding="utf-8")
            env = os.environ.copy()
            env["REPO_ROOT"] = str(REPO)
            env["TRACE_ENABLED"] = "0"
            proc = subprocess.run(
                [str(launcher), str(candidate)],
                cwd=wd,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=10,
            )
            attempt_files = sorted((wd / "validate_timing").glob("agentic_attempt__*.json"))
            attempt_payload = {}
            if attempt_files:
                attempt_payload = json.loads(attempt_files[0].read_text(encoding="utf-8"))
            cases.append(_check(
                "workdir_validator_launcher_writes_attempt_log",
                (proc.returncode == 0
                 and bool(attempt_files)
                 and attempt_payload.get("status") == "ended"
                 and attempt_payload.get("rc") == 0
                 and isinstance(attempt_payload.get("total_ms"), (int, float))),
                f"rc={proc.returncode} stdout={proc.stdout[:200]!r} stderr={proc.stderr[:200]!r} "
                f"attempt_files={[p.name for p in attempt_files]} payload={attempt_payload!r}",
            ))
        finally:
            if wd is not None:
                shutil.rmtree(wd, ignore_errors=True)
    finally:
        shutil.rmtree(fake_repo2, ignore_errors=True)

    # ----- 8a. _copy_timing_artifacts moves attempt logs from tmpdir to repo output. -----
    fake_repo_copy = _make_tmp_repo()
    with tempfile.TemporaryDirectory(prefix="ca_timing_copy_") as td:
        workdir_copy = Path(td)
        src_dir = workdir_copy / "validate_timing"
        src_dir.mkdir(parents=True, exist_ok=True)
        src_file = src_dir / "agentic_attempt__candidate__copy.json"
        src_file.write_text(json.dumps({"type": "agentic_validator_attempt"}), encoding="utf-8")
        try:
            with mock.patch.dict(os.environ, {"VALIDATE_TIMING": "1"}):
                ca._copy_timing_artifacts(workdir_copy, fake_repo_copy)
            dst_file = fake_repo_copy / "output" / "validate_timing" / src_file.name
            cases.append(_check(
                "copy_timing_artifacts_copies_agentic_attempt",
                dst_file.exists(),
                f"expected copied file at {dst_file}",
            ))
        finally:
            shutil.rmtree(fake_repo_copy, ignore_errors=True)

    # ----- 8c. codex child PATH prepends current interpreter dir (venv first) -----
    fake_repo3 = _make_tmp_repo()
    captured: dict[str, object] = {}

    class FakePopen:
        def __init__(self, args, **kwargs):
            captured["args"] = args
            captured["env"] = kwargs.get("env") or {}
            out_path = Path(args[args.index("--output-last-message") + 1])
            out_path.write_text(
                json.dumps({
                    "ok": True,
                    "config": {"site": "https://example.com/", "strategy": "httpx_html"},
                    "attempts": [{"i": 1, "validate_ok": True, "error": ""}],
                    "stop_reason": "validate_pass",
                }),
                encoding="utf-8",
            )
            self.returncode = 0

        def communicate(self, input=None, timeout=None):  # noqa: A002 - subprocess API
            return (
                '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":2}}\n',
                "",
            )

        def kill(self):
            self.returncode = -9

    async def fake_validate_built_config(config, *, digest=None, fetch_articles=1):
        return type("Report", (), {"ok": True})()

    try:
        with mock.patch.object(ca, "_codex_preflight", return_value="codex-cli test"), \
             mock.patch.object(ca, "_codex_bin", return_value="codex"), \
             mock.patch.object(ca.subprocess, "Popen", FakePopen), \
             mock.patch.object(ca, "validate_built_config", fake_validate_built_config), \
             mock.patch.dict(os.environ, {
                 "VALIDATE_TIMING": "1",
                 "VALIDATE_TIMING_PRESERVE_WORKDIR": "1",
             }):
            asyncio.run(ca.run_codex_agentic(
                digest={"url": "https://example.com/"},
                slug="pathslug",
                url="https://example.com/",
                repo=fake_repo3,
                timeout_s=5.0,
            ))
        child_env = captured.get("env") or {}
        child_path = str(child_env.get("PATH", ""))
        expected_first = str(Path(sys.executable).parent)
        popen_args = captured.get("args") or []
        cases.append(_check(
            "codex_child_path_prepends_sys_executable_dir",
            child_path.split(os.pathsep)[0] == expected_first,
            f"PATH first={child_path.split(os.pathsep)[0] if child_path else ''!r}, expected={expected_first!r}",
        ))
        cases.append(_check(
            "codex_child_uses_platform_sandbox_args",
            all(arg in popen_args for arg in ca._sandbox_args(Path(popen_args[popen_args.index("-C") + 1]))),
            f"args={popen_args!r}",
        ))
        run_logs = sorted((fake_repo3 / "output" / "validate_timing").glob("agentic_run__pathslug__*.json"))
        snapshots = sorted((fake_repo3 / "output" / "validate_timing" / "agentic_workdirs").glob("pathslug__*"))
        run_log = json.loads(run_logs[0].read_text(encoding="utf-8")) if run_logs else {}
        cases.append(_check(
            "codex_agentic_timing_logs_agent_input_and_execution",
            (bool(run_logs)
             and run_log.get("slug") == "pathslug"
             and run_log.get("digest") == {"url": "https://example.com/"}
             and isinstance(run_log.get("codex_args"), list)
             and "TASK:" in str(run_log.get("user_prompt") or "")
             and run_log.get("rc") == 0
             and bool(run_log.get("stdout_tail"))),
            f"run_logs={[p.name for p in run_logs]} run_log={run_log!r}",
        ))
        cases.append(_check(
            "codex_agentic_preserves_workdir_snapshot",
            (bool(snapshots)
             and (snapshots[0] / "codex_stdout.jsonl").exists()
             and (snapshots[0] / "codex_stderr.txt").exists()
             and (snapshots[0] / "codex_run_meta.json").exists()
             and (snapshots[0] / "last.json").exists()),
            f"snapshots={[str(p) for p in snapshots]}",
        ))
    finally:
        shutil.rmtree(fake_repo3, ignore_errors=True)

    # ----- 8d. ok=true final message can point at candidate.json instead of echoing config -----
    fake_repo4 = _make_tmp_repo()

    class CandidatePathPopen:
        def __init__(self, args, **kwargs):
            out_path = Path(args[args.index("--output-last-message") + 1])
            workdir = out_path.parent
            (workdir / "candidate.json").write_text(
                json.dumps({
                    "site": "https://example.com/",
                    "strategy": "httpx_html",
                    "list": {"selector": ".post"},
                }),
                encoding="utf-8",
            )
            out_path.write_text(
                json.dumps({
                    "ok": True,
                    "candidate_path": "./candidate.json",
                    "attempts": [{"i": 1, "validate_ok": True, "error": ""}],
                    "stop_reason": "validate_pass",
                }),
                encoding="utf-8",
            )
            self.returncode = 0

        def communicate(self, input=None, timeout=None):  # noqa: A002 - subprocess API
            return (
                '{"type":"turn.completed","usage":{"input_tokens":3,"output_tokens":4}}\n',
                "",
            )

        def kill(self):
            self.returncode = -9

    try:
        with mock.patch.object(ca, "_codex_preflight", return_value="codex-cli test"), \
             mock.patch.object(ca, "_codex_bin", return_value="codex"), \
             mock.patch.object(ca.subprocess, "Popen", CandidatePathPopen), \
             mock.patch.object(ca, "validate_built_config", fake_validate_built_config):
            result = asyncio.run(ca.run_codex_agentic(
                digest={"url": "https://example.com/"},
                slug="candidatepathslug",
                url="https://example.com/",
                repo=fake_repo4,
                timeout_s=5.0,
            ))
        cases.append(_check(
            "codex_final_can_reference_candidate_path",
            (result.config.get("list") == {"selector": ".post"}
             and result.stop_reason == "validate_pass"
             and result.attempts == [{"i": 1, "validate_ok": True, "error": ""}]
             and result.prompt_tokens == 3
             and result.completion_tokens == 4),
            f"config={result.config!r} stop={result.stop_reason!r} attempts={result.attempts!r} "
            f"tokens={result.prompt_tokens}+{result.completion_tokens}",
        ))
    finally:
        shutil.rmtree(fake_repo4, ignore_errors=True)

    # ----- 8b. GenerationError carries token/wall meta on failure path -----
    err = ca.GenerationError(
        "fake fail",
        last_config={"x": 1},
        last_feedback="why",
        prompt_tokens=1234,
        completion_tokens=56,
        wall_s=12.5,
        stop_reason="max_cycles",
        codex_version="codex-cli 0.130.0",
    )
    cases.append(_check(
        "generation_error_carries_meta",
        (err.prompt_tokens == 1234 and err.completion_tokens == 56
         and err.wall_s == 12.5 and err.stop_reason == "max_cycles"
         and err.codex_version == "codex-cli 0.130.0"
         and err.last_config == {"x": 1} and err.last_feedback == "why"),
        f"got tokens={err.prompt_tokens}+{err.completion_tokens} wall={err.wall_s} "
        f"stop={err.stop_reason} ver={err.codex_version}",
    ))

    # Default values preserved when meta omitted (backwards compat).
    err_bare = ca.GenerationError("bare")
    cases.append(_check(
        "generation_error_default_meta_zero",
        (err_bare.prompt_tokens == 0 and err_bare.completion_tokens == 0
         and err_bare.wall_s == 0.0 and err_bare.stop_reason == ""
         and err_bare.codex_version == ""),
        f"got tokens={err_bare.prompt_tokens}+{err_bare.completion_tokens} "
        f"wall={err_bare.wall_s} stop={err_bare.stop_reason!r}",
    ))

    # ----- 9. _sum_usage: multi-turn 누적 -----
    stdout_jsonl = "\n".join([
        '{"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 50}}',
        '{"type": "turn.completed", "usage": {"input_tokens": 200, "output_tokens": 80}}',
        '{"type": "other"}',
    ])
    in_t, out_t = ca._sum_usage(stdout_jsonl)
    cases.append(_check(
        "sum_usage_multi_turn",
        in_t == 300 and out_t == 130,
        f"got input={in_t} output={out_t} (expected 300, 130)",
    ))

    # ----- 10. validate_config internal timeout emits JSON and rc=0 -----
    cases.append(_check(
        "validate_config_internal_timeout_default_25s",
        int(validate_config_cli.INTERNAL_TIMEOUT_S) == 25,
        f"got {validate_config_cli.INTERNAL_TIMEOUT_S!r}",
    ))
    with tempfile.TemporaryDirectory(prefix="validate_timeout_test_") as td:
        candidate = Path(td) / "candidate.json"
        candidate.write_text(json.dumps({"site": "https://example.com/"}), encoding="utf-8")
        code = f"""
import asyncio
import sys
from pathlib import Path
import scripts.validate_config as vc

vc.INTERNAL_TIMEOUT_S = 1.0

async def slow_validate_built_config(cfg, *, digest=None, fetch_articles=1):
    await asyncio.sleep(65)

vc.validate_built_config = slow_validate_built_config
sys.exit(vc.main(["validate_config.py", {str(candidate)!r}]))
"""
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
        )
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            payload = {}
        cases.append(_check(
            "validate_config_internal_timeout_json_rc0",
            (proc.returncode == 0
             and payload.get("ok") is False
             and payload.get("error") == "validate_internal_timeout_1s"
             and payload.get("checks") == []
             and payload.get("sample_posts") == []),
            f"rc={proc.returncode} stdout={proc.stdout!r} stderr={proc.stderr!r}",
        ))

    with tempfile.TemporaryDirectory(prefix="validate_cli_path_test_") as td:
        candidate = Path(td) / "candidate.json"
        candidate.write_text(json.dumps({
            "version": 1,
            "site": "example.com",
            "board": "root",
            "strategy": "httpx_html",
        }), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "scripts/validate_config.py", str(candidate)],
            cwd=REPO,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
        )
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            payload = {}
        cases.append(_check(
            "validate_config_direct_script_imports_repo_root",
            (proc.returncode == 0
             and payload.get("ok") is False
             and "ModuleNotFoundError" not in proc.stderr),
            f"rc={proc.returncode} stdout={proc.stdout!r} stderr={proc.stderr!r}",
        ))

    # POSIX hard alarm catches sync blocks that prevent asyncio.wait_for from ticking.
    if hasattr(signal, "SIGALRM") and hasattr(signal, "setitimer"):
        with tempfile.TemporaryDirectory(prefix="validate_hard_timeout_test_") as td:
            candidate = Path(td) / "candidate.json"
            candidate.write_text(json.dumps({"site": "https://example.com/"}), encoding="utf-8")
            code = f"""
import asyncio
import sys
import time
import scripts.validate_config as vc

vc.INTERNAL_TIMEOUT_S = 1.0

async def blocking_validate_built_config(cfg, *, digest=None, fetch_articles=1):
    time.sleep(65)

vc.validate_built_config = blocking_validate_built_config
sys.exit(vc.main(["validate_config.py", {str(candidate)!r}]))
"""
            proc = subprocess.run(
                [sys.executable, "-c", code],
                cwd=REPO,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=5,
            )
            try:
                payload = json.loads(proc.stdout)
            except json.JSONDecodeError:
                payload = {}
            cases.append(_check(
                "validate_config_hard_timeout_blocks_json_rc0",
                (proc.returncode == 0
                 and payload.get("ok") is False
                 and payload.get("error") == "validate_internal_timeout_1s"),
                f"rc={proc.returncode} stdout={proc.stdout!r} stderr={proc.stderr!r}",
            ))
    else:
        cases.append(_check(
            "validate_config_hard_timeout_posix_only",
            True,
            "SIGALRM unavailable on this platform",
        ))

    # ----- 11. codex agentic classifier marks closed session stdin as transient network -----
    closed_stdin_err = ca._codex_classify_error(
        "error=write_stdin failed: stdin is closed for this session; rerun exec_command with tty=true",
        "",
        1,
    )
    cases.append(_check(
        "codex_classify_session_stdin_closed",
        (isinstance(closed_stdin_err, LLMNetworkError)
         and "codex_agentic_transient_session_stdin_closed" in str(closed_stdin_err)),
        f"got {type(closed_stdin_err).__name__}: {closed_stdin_err}",
    ))

    # ----- 11b. one transient codex session fault retries with a fresh subprocess. -----
    fake_repo_retry = _make_tmp_repo()
    retry_calls = {"n": 0}

    class TransientThenSuccessPopen:
        def __init__(self, args, **kwargs):
            retry_calls["n"] += 1
            self.pid = 999998
            self.returncode = 1
            self._attempt = retry_calls["n"]
            out_path = Path(args[args.index("--output-last-message") + 1])
            if self._attempt == 2:
                out_path.write_text(
                    json.dumps({
                        "ok": True,
                        "config": {"site": "https://example.com/", "strategy": "httpx_html"},
                        "attempts": [{"i": 1, "validate_ok": True, "error": ""}],
                        "stop_reason": "validate_pass",
                    }),
                    encoding="utf-8",
                )

        def communicate(self, input=None, timeout=None):  # noqa: A002 - subprocess API
            if self._attempt == 1:
                self.returncode = 1
                return (
                    "",
                    "error=write_stdin failed: stdin is closed for this session; "
                    "rerun exec_command with tty=true",
                )
            self.returncode = 0
            return (
                '{"type":"turn.completed","usage":{"input_tokens":5,"output_tokens":6}}\n',
                "",
            )

        def kill(self):
            self.returncode = -9

    try:
        with mock.patch.object(ca, "_codex_preflight", return_value="codex-cli test"), \
             mock.patch.object(ca, "_codex_bin", return_value="codex"), \
             mock.patch.object(ca.subprocess, "Popen", TransientThenSuccessPopen), \
             mock.patch.object(ca, "validate_built_config", fake_validate_built_config):
            retry_result = asyncio.run(ca.run_codex_agentic(
                digest={"url": "https://example.com/"},
                slug="transientretry",
                url="https://example.com/",
                repo=fake_repo_retry,
                timeout_s=5.0,
            ))
        cases.append(_check(
            "codex_transient_session_stdin_closed_retries_once",
            (retry_calls["n"] == 2
             and retry_result.stop_reason == "validate_pass"
             and retry_result.prompt_tokens == 5
             and retry_result.completion_tokens == 6),
            f"calls={retry_calls['n']} result={retry_result!r}",
        ))
    finally:
        shutil.rmtree(fake_repo_retry, ignore_errors=True)

    # ----- 12. codex startup-only timeout is transient -----
    fake_repo5 = _make_tmp_repo()

    class StartupTimeoutPopen:
        def __init__(self, args, **kwargs):
            self.pid = 999999
            self.returncode = None
            self._calls = 0

        def communicate(self, input=None, timeout=None):  # noqa: A002 - subprocess API
            self._calls += 1
            if self._calls == 1:
                raise subprocess.TimeoutExpired(cmd="codex exec", timeout=timeout)
            self.returncode = -9
            return ("", "Reading prompt from stdin...\n")

        def kill(self):
            self.returncode = -9

    try:
        with mock.patch.object(ca, "_codex_preflight", return_value="codex-cli test"), \
             mock.patch.object(ca, "_codex_bin", return_value="codex"), \
             mock.patch.object(ca, "_kill_process_tree", lambda pid: None), \
             mock.patch.object(ca.subprocess, "Popen", StartupTimeoutPopen):
            try:
                asyncio.run(ca.run_codex_agentic(
                    digest={"url": "https://example.com/"},
                    slug="startuptimeout",
                    url="https://example.com/",
                    repo=fake_repo5,
                    timeout_s=0.01,
                ))
                timeout_err = None
            except LLMNetworkError as e:
                timeout_err = e
        cases.append(_check(
            "codex_timeout_classified_transient",
            (timeout_err is not None and "codex_agentic_transient_timeout" in str(timeout_err)),
            f"got {type(timeout_err).__name__ if timeout_err else None}: {timeout_err}",
        ))
    finally:
        shutil.rmtree(fake_repo5, ignore_errors=True)

    return cases


def test_codex_agentic_cases():
    results = run()
    failed = [(n, d) for n, ok, d in results if not ok]
    assert not failed, "\n".join(f"{n}: {d}" for n, d in failed)


if __name__ == "__main__":
    results = run()
    failed = [(n, d) for n, ok, d in results if not ok]
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {d}")
    if failed:
        print(f"\n{len(failed)} FAILED")
        sys.exit(1)
    print(f"\n{len(results)} passed")
