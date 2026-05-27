"""playwright_html route response header rewrite helpers."""
from __future__ import annotations


def test_route_rewrite_headers_override_case_insensitive() -> None:
    from engine.strategies.playwright_html import _rewrite_response_headers

    merged = _rewrite_response_headers(
        {"Content-Type": "text/html", "cache-control": "max-age=60"},
        {"content-type": "application/javascript"},
    )

    assert merged == {
        "cache-control": "max-age=60",
        "content-type": "application/javascript",
    }


def test_route_rewrite_fallback_body_only_for_html_js_response() -> None:
    from engine.strategies.playwright_html import _fallback_body_for_html_js_response

    fallback = "window['metric-utils']={reportH5SlsMsg:function(){}};"

    assert _fallback_body_for_html_js_response(
        "https://cdn.example.com/app.js",
        {"Content-Type": "text/html"},
        {"content-type": "application/javascript"},
        fallback,
        "<!DOCTYPE html><html></html>",
    ) == fallback
    assert _fallback_body_for_html_js_response(
        "https://cdn.example.com/app.css",
        {"content-type": "text/html"},
        {"content-type": "application/javascript"},
        fallback,
        "<!DOCTYPE html><html></html>",
    ) is None
    assert _fallback_body_for_html_js_response(
        "https://cdn.example.com/app.js",
        {"content-type": "application/javascript"},
        {"content-type": "application/javascript"},
        fallback,
        "window.ok = true;",
    ) is None
    assert _fallback_body_for_html_js_response(
        "https://cdn.example.com/app.js",
        {"content-type": "text/html"},
        {"content-type": "application/javascript"},
        fallback,
        "window.realJsButWrongMime = true;",
    ) is None


covers = ["playwright_route_rewrite_response_headers"]


def run() -> list[tuple[str, bool, str]]:
    from engine.strategies.playwright_html import _rewrite_response_headers

    merged = _rewrite_response_headers(
        {"Content-Type": "text/html", "cache-control": "max-age=60"},
        {"content-type": "application/javascript"},
    )
    return [
        (
            "route_rewrite_headers_override_case_insensitive",
            merged == {"cache-control": "max-age=60", "content-type": "application/javascript"},
            repr(merged),
        )
    ]
