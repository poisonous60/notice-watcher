"""Regression tests for hand-config terminal-decision instructions."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


ROOT = Path(__file__).resolve().parent.parent.parent


def run() -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []
    skill = (ROOT / ".claude" / "skills" / "hand-config" / "SKILL.md").read_text(encoding="utf-8")
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    cases.append((
        "skill_has_terminal_action_freeze",
        "terminal action freeze" in skill,
        skill[:1200],
    ))
    cases.append((
        "skill_requires_live_probe_before_terminal",
        "live 확인" in skill and "probe artifact" in skill and "stale snapshot" in skill,
        skill[:2400],
    ))
    cases.append((
        "skill_blocks_generic_go_as_terminal_approval",
        "generic `진행해`" in skill and "slug별 terminal action" in skill,
        skill[:3600],
    ))
    cases.append((
        "skill_warns_one_observation_is_not_rejected",
        "raw 503/DNS/timeout" in skill and "첫 진단 pass" in skill and "REJECTED 가능" in skill,
        skill[:4800],
    ))
    cases.append((
        "claude_memory_has_terminal_action_freeze",
        "hand-config terminal action freeze" in claude
        and "generic `진행해`" in claude
        and "raw 503/DNS/timeout" in claude
        and "첫 진단 pass" in claude,
        claude[:4200],
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
