"""Dashboard skill prompt regression tests."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dashboard import prompts  # noqa: E402


def run() -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []

    triage_prompt = prompts.hand_config_triage_queue(failed_slugs=["slug_a"])
    catalog_prompt = prompts.catalog_run_and_fix(catalog_name="sample", untried=3, failed=0, bug=0)
    triage_claude = prompts.hand_config_triage_queue_claude(failed_slugs=["slug_a", "slug_b"])
    catalog_claude = prompts.catalog_run_and_fix_claude(catalog_name="sample", untried=3, failed=0, bug=0)

    # Claude 직접 모드: codex 위임 어휘 없어야 함
    for name, text in (("triage_claude", triage_claude), ("catalog_claude", catalog_claude)):
        cases.append((
            f"{name}_no_codex_handoff",
            "codex_handoff" not in text and "codex_watch" not in text,
            text,
        ))
        cases.append((
            f"{name}_no_codex_delegate_phrase",
            "codex 위임 모드" not in text and "codex 보이는 창" not in text,
            text,
        ))
        cases.append((
            f"{name}_declares_claude_direct",
            "claude 직접 모드" in text and "codex 위임 X" in text,
            text,
        ))
        cases.append((
            f"{name}_chunk_size_explicit",
            "slug 1~3개" in text,
            text,
        ))
        cases.append((
            f"{name}_has_terminal_freeze",
            "terminal action freeze" in text and "live 확인" in text,
            text,
        ))
        cases.append((
            f"{name}_has_terminal_state_obligation",
            "registered" in text and "Later" in text and "gate-fail" in text and "REJECTED" in text,
            text,
        ))
        cases.append((
            f"{name}_mentions_subagent_optional",
            "cavecrew-investigator" in text and "강제 X" in text,
            text,
        ))

    for name, text in (
        ("triage_queue", triage_prompt),
        ("catalog_runfix", catalog_prompt),
    ):
        cases.append((
            f"{name}_uses_full_auto_batch",
            "api_loop_once → agentic" in text,
            text,
        ))
        cases.append((
            f"{name}_does_not_recommend_no_agentic_for_batch",
            "--reuse-probe --no-agentic --max-attempts 1" not in text,
            text,
        ))
        cases.append((
            f"{name}_mentions_compact_agent_context",
            "agent 입력" in text and "failure_packet" in text,
            text,
        ))
        cases.append((
            f"{name}_does_not_use_allow_list_model",
            "ALLOW-LIST" not in text and "이 파일만 편집" not in text and "파일셋이 ALLOW-LIST" not in text,
            text,
        ))
        cases.append((
            f"{name}_uses_worktree_free_edit_review_model",
            "--worktree" in text and "필요한 repo 파일을 자유롭게 수정" in text and "git diff" in text,
            text,
        ))
        cases.append((
            f"{name}_has_terminal_decision_freeze",
            "terminal action freeze" in text
            and "live 확인" in text
            and "generic `진행해`" in text
            and "raw 503/DNS/timeout" in text
            and "첫 진단 pass" in text,
            text,
        ))

    return cases


if __name__ == "__main__":
    results = run()
    failed = [(n, d) for n, ok, d in results if not ok]
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {'' if ok else d[:300]}")
    if failed:
        print(f"\n{len(failed)} FAILED")
        sys.exit(1)
    print(f"\n{len(results)} passed")
