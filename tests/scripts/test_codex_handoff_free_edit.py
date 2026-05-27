"""Regression tests for Codex handoff prompt scope."""
from __future__ import annotations

import sys
import inspect
from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts import codex_handoff  # noqa: E402


FORBIDDEN = (
    "ALLOW-LIST",
    "allow-list",
    "이 파일만 편집",
    "나머지 금지",
    "밖이라",
    "청크 멤버 파일만",
)


def run() -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []

    generic = codex_handoff.build_generic("batch gen_fail 3건 분석")
    batch = codex_handoff.build_handconfig_batch(
        [
            {"slug": "slug_a", "url": "https://example.com/news", "board": "news"},
            {"slug": "slug_b", "url": "https://example.org/news", "board": "news"},
        ],
        "host:example",
    )

    for name, text in (("generic", generic), ("handconfig_batch", batch)):
        for token in FORBIDDEN:
            cases.append((f"{name}_omits_{token}", token not in text, text))
        cases.append((
            f"{name}_allows_repo_wide_track_b_edits",
            "필요한 repo 파일을 자유롭게 수정" in text,
            text,
        ))
        cases.append((
            f"{name}_uses_diff_review_as_enforcement",
            "git diff" in text and "Claude" in text and "검토" in text,
            text,
        ))

    cases.append((
        "launch_defaults_to_worktree",
        codex_handoff.launch.__defaults__ is not None
        and codex_handoff.launch.__defaults__[2] is True,
        str(codex_handoff.launch.__defaults__),
    ))
    cases.append((
        "cli_has_explicit_no_worktree_escape_hatch",
        "--no-worktree" in inspect.getsource(codex_handoff.main),
        inspect.getsource(codex_handoff.main),
    ))
    prompt_file = codex_handoff.OUT / "_test_codex_handoff_free_edit_task.md"
    prompt_file.write_text("test task", encoding="utf-8")
    try:
        buf = StringIO()
        with redirect_stdout(buf):
            rc = codex_handoff.main(["generic", "--task-file", str(prompt_file)])
        stdout = buf.getvalue()
        cases.append((
            "manual_run_hint_uses_worktree",
            rc == 0 and "-Worktree" in stdout and "-WorktreeTag" in stdout,
            stdout,
        ))
    finally:
        prompt_file.unlink(missing_ok=True)
        generated = codex_handoff.OUT / "codex_generic_test-codex-handoff-free-edit-task_prompt.txt"
        generated.unlink(missing_ok=True)

    runner = (Path(__file__).resolve().parent.parent.parent / "scripts" / "codex_run.ps1").read_text(encoding="utf-8")
    cases.append((
        "runner_review_hint_uses_three_dot_diff",
        "git diff main...$wtBranch" in runner and "git diff main..$wtBranch" not in runner,
        runner,
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
