"""probe.fetch_headless._dismiss_consent_modals — cookie modal click unblock."""
from __future__ import annotations


class _FakePage:
    def __init__(self, dismissed: int):
        self.dismissed = dismissed
        self.waited = 0

    def evaluate(self, _script):
        return self.dismissed

    def wait_for_timeout(self, ms: int) -> None:
        self.waited += ms


def run() -> list[tuple[str, bool, str]]:
    from probe.fetch_headless import _dismiss_consent_modals

    cases: list[tuple[str, bool, str]] = []

    page = _FakePage(1)
    count = _dismiss_consent_modals(page)
    cases.append(("returns_dismissed_count", count == 1, f"got {count}"))
    cases.append(("waits_after_dismiss", page.waited > 0, f"waited={page.waited}"))

    page_zero = _FakePage(0)
    count_zero = _dismiss_consent_modals(page_zero)
    cases.append(("zero_when_no_banner", count_zero == 0 and page_zero.waited == 0,
                  f"count={count_zero} waited={page_zero.waited}"))

    return cases
