from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
scripts_mod = sys.modules.get("scripts")
if scripts_mod is not None and not str(getattr(scripts_mod, "__file__", "")).startswith(str(ROOT / "scripts")):
    del sys.modules["scripts"]


def test_canonical_reject_note_tells_user_to_retry_watch_hint():
    ok, detail = _exercise_rejected_hint()
    assert ok, detail


def _exercise_rejected_hint() -> tuple[bool, str]:
    sys.path.insert(0, str(ROOT))
    scripts_mod = sys.modules.get("scripts")
    if scripts_mod is not None:
        del sys.modules["scripts"]
    from bot import site_ops

    note = site_ops.public_rejected_note({
        "reason": "canonical_url_change",
        "note": "gate: canonical_url_change",
        "hint": "https://filecoin.io/blog/",
    })

    ok = "URL이 바뀐 것 같아요" in note and "/watch https://filecoin.io/blog/" in note
    return ok, note


def run() -> list[tuple[str, bool, str]]:
    ok, detail = _exercise_rejected_hint()
    return [("canonical_reject_note_retry_hint", ok, detail)]


if __name__ == "__main__":
    results = run()
    failed = [(n, d) for n, ok, d in results if not ok]
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {d}")
    raise SystemExit(0 if not failed else 1)
