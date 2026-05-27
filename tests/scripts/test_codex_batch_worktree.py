"""Regression test for batch Codex launch isolation."""
from __future__ import annotations

import sys
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts import codex_batch  # noqa: E402


def run() -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []
    calls: list[dict] = []

    orig_partition = codex_batch.partition
    orig_pending_chunks = codex_batch._pending_chunks
    orig_chunk_prompt = codex_batch._chunk_prompt
    orig_launch = codex_batch.codex_handoff.launch

    groups = OrderedDict([
        ("host:example.com", [{"slug": "slug_a", "url": "https://example.com/news", "board": "news"}])
    ])

    try:
        codex_batch.partition = lambda slugs: groups  # type: ignore[assignment]
        codex_batch._pending_chunks = lambda g: list(g.items())  # type: ignore[assignment]
        codex_batch._chunk_prompt = lambda key, members: Path("output/fake_prompt.txt")  # type: ignore[assignment]

        def fake_launch(path: Path, title: str, **kwargs) -> Path:
            calls.append({"path": path, "title": title, **kwargs})
            return Path("output/fake_prompt.result.md")

        codex_batch.codex_handoff.launch = fake_launch  # type: ignore[assignment]

        rc = codex_batch.cmd_launch(["slug_a"], max_parallel=1)
        cases.append(("launch_returns_zero", rc == 0, str(rc)))
        cases.append(("launch_called_once", len(calls) == 1, str(calls)))
        cases.append(("launch_uses_worktree", calls and calls[0].get("worktree") is True, str(calls)))
        cases.append(("launch_sets_worktree_tag", calls and bool(calls[0].get("worktree_tag")), str(calls)))
    finally:
        codex_batch.partition = orig_partition  # type: ignore[assignment]
        codex_batch._pending_chunks = orig_pending_chunks  # type: ignore[assignment]
        codex_batch._chunk_prompt = orig_chunk_prompt  # type: ignore[assignment]
        codex_batch.codex_handoff.launch = orig_launch  # type: ignore[assignment]

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
