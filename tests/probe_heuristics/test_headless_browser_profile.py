"""probe.fetch_headless browser profile and Cloudflare wait markers."""
from __future__ import annotations


covers = ["headless_browser_profile", "cloudflare_interstitial_wait"]


class _FakePage:
    def __init__(self, *, title: str, html: str, url: str = "https://example.com/"):
        self._title = title
        self._html = html
        self.url = url

    def title(self) -> str:
        return self._title

    def content(self) -> str:
        return self._html


def run() -> list[tuple[str, bool, str]]:
    from probe.fetch_headless import _context_kwargs, _is_cloudflare_interstitial

    cases: list[tuple[str, bool, str]] = []

    kwargs = _context_kwargs(storage_state_path=None)
    cases.append((
        "uses_realistic_chrome_ua",
        "Chrome/148." in kwargs.get("user_agent", ""),
        kwargs.get("user_agent", ""),
    ))
    cases.append((
        "sets_accept_language_timezone_screen",
        kwargs.get("timezone_id") == "Asia/Seoul"
        and kwargs.get("screen", {}).get("width") == 1365
        and "Accept-Language" in kwargs.get("extra_http_headers", {}),
        repr(kwargs),
    ))

    challenge, turnstile = _is_cloudflare_interstitial(_FakePage(
        title="Just a moment...",
        html='<script src="/cdn-cgi/challenge-platform/h/g/orchestrate/__cf_chl/v1"></script>',
    ))
    cases.append(("detects_cloudflare_js_interstitial", challenge and not turnstile,
                  f"challenge={challenge}, turnstile={turnstile}"))

    challenge, turnstile = _is_cloudflare_interstitial(_FakePage(
        title="Skeb - Request Box",
        html='<div class="cf-turnstile" data-sitekey="x"></div>',
    ))
    cases.append(("detects_turnstile_as_not_auto_clearable", turnstile,
                  f"challenge={challenge}, turnstile={turnstile}"))

    challenge, turnstile = _is_cloudflare_interstitial(_FakePage(
        title="News",
        html='<main><a href="/news/1">Release note</a></main>',
    ))
    cases.append(("normal_page_not_challenge", not challenge and not turnstile,
                  f"challenge={challenge}, turnstile={turnstile}"))

    return cases
