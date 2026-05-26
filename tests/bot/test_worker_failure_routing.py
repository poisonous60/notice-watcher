import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if "tests\\scripts" in str(getattr(sys.modules.get("scripts"), "__file__", "")):
    sys.modules.pop("scripts", None)

from bot.worker import _should_append_triage_queue_for_register_failure


def test_capability_blocked_register_failure_skips_active_triage_queue():
    assert not _should_append_triage_queue_for_register_failure(5)


def test_gen_fail_register_failure_still_goes_to_active_triage_queue():
    assert _should_append_triage_queue_for_register_failure(1)


def test_terminal_reject_and_bug_failures_skip_active_triage_queue():
    for rc in (2, 3, 4, -4, -3, -2, -1):
        assert not _should_append_triage_queue_for_register_failure(rc)
