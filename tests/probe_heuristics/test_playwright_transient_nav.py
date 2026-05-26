"""playwright_html transient navigation error classifier."""
from __future__ import annotations


covers = ["playwright_transient_nav_error_retry"]


def run() -> list[tuple[str, bool, str]]:
    from engine.strategies.playwright_html import _is_transient_nav_error

    cases: list[tuple[str, bool, str]] = []
    dns = RuntimeError("Error: Page.goto: net::ERR_NAME_NOT_RESOLVED at https://x.test/news/")
    eai = RuntimeError("ConnectError: [Errno -3] Temporary failure in name resolution")
    timeout = RuntimeError("Timeout 15000ms exceeded while waiting for domcontentloaded")

    cases.append(("chromium_dns_is_transient", _is_transient_nav_error(dns), str(dns)))
    cases.append(("eai_again_is_transient", _is_transient_nav_error(eai), str(eai)))
    cases.append(("navigation_timeout_not_retried_here", not _is_transient_nav_error(timeout), str(timeout)))
    return cases
