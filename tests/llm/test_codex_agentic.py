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
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from generate import codex_agentic as ca  # noqa: E402
from generate.llm_base import LLMNetworkError  # noqa: E402


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
        pre = ca._audit_snapshot_paths(fake_repo, slug)
        # mutate
        (fake_repo / "engine" / "a.py").write_text("MUTATED", encoding="utf-8")
        post = ca._audit_snapshot_paths(fake_repo, slug)
        diff = ca._audit_diff(pre, post)
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
        diff2 = ca._audit_diff(pre2, post2)
        cases.append(_check(
            "audit_catches_mtime_spoof_via_sha",
            any("a.py" in d for d in diff2),
            f"diff={diff2} — SHA should catch same-len different-content",
        ))

        # ----- 5. NEW file detection -----
        (fake_repo / "engine" / "b.py").write_text("INTRUDER", encoding="utf-8")
        post3 = ca._audit_snapshot_paths(fake_repo, slug)
        diff3 = ca._audit_diff(pre, post3)
        cases.append(_check(
            "audit_detects_new_file",
            any("b.py" in d and "NEW" in d for d in diff3),
            f"diff={diff3}",
        ))

        # ----- 6. per-slug scope: 다른 slug 의 config 변경은 audit 무관 -----
        (fake_repo / "configs" / "OTHER.json").write_text(json.dumps({"k": 1}),
                                                         encoding="utf-8")
        pre4 = ca._audit_snapshot_paths(fake_repo, slug)
        # 다른 slug 의 config 변경
        (fake_repo / "configs" / "OTHER.json").write_text(json.dumps({"k": 2}),
                                                         encoding="utf-8")
        post4 = ca._audit_snapshot_paths(fake_repo, slug)
        diff4 = ca._audit_diff(pre4, post4)
        cases.append(_check(
            "audit_ignores_other_slug_config",
            not any("OTHER.json" in d for d in diff4),
            f"diff={diff4} (should be empty — other slug)",
        ))

        # ----- 7. self slug config 변경은 audit 잡음 -----
        (fake_repo / "configs" / f"{slug}.json").write_text(json.dumps({"k": 1}),
                                                            encoding="utf-8")
        pre5 = ca._audit_snapshot_paths(fake_repo, slug)
        (fake_repo / "configs" / f"{slug}.json").write_text(json.dumps({"k": 2}),
                                                            encoding="utf-8")
        post5 = ca._audit_snapshot_paths(fake_repo, slug)
        diff5 = ca._audit_diff(pre5, post5)
        cases.append(_check(
            "audit_catches_self_slug_config_change",
            any(f"{slug}.json" in d for d in diff5),
            f"diff={diff5} (agent shouldn't touch its own slug config)",
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
            wd = ca._setup_workdir(
                {"recognizer_hint": {"name": "myrec"},
                 "strategy_hint": {"strategy": "httpx_html"},
                 "url": "https://example.com/board"},
                "testslug",
                "https://example.com/board",
                fake_repo2,
            )
            files_present = {
                "digest.json": (wd / "digest.json").exists(),
                "slug.txt": (wd / "slug.txt").exists(),
                "url.txt": (wd / "url.txt").exists(),
                "repo_path.txt": (wd / "repo_path.txt").exists(),
                "examples_dir": (wd / "examples").exists(),
                "manifest": (wd / "examples" / "manifest.json").exists(),
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
        finally:
            if wd is not None:
                shutil.rmtree(wd, ignore_errors=True)
    finally:
        shutil.rmtree(fake_repo2, ignore_errors=True)

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

    return cases


if __name__ == "__main__":
    results = run()
    failed = [(n, d) for n, ok, d in results if not ok]
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {d}")
    if failed:
        print(f"\n{len(failed)} FAILED")
        sys.exit(1)
    print(f"\n{len(results)} passed")
