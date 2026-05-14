"""probe.extract._is_js_href — javascript:/#/빈값 판정."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import _is_js_href

    cases: list[tuple[str, bool, str]] = []

    cases.append(("empty_str", _is_js_href("") is True, ""))
    cases.append(("none", _is_js_href(None) is True, ""))
    cases.append(("whitespace", _is_js_href("   ") is True, ""))
    cases.append(("hash_only", _is_js_href("#") is True, ""))
    cases.append(("hash_fragment", _is_js_href("#section1") is True, ""))
    cases.append(("javascript_lower", _is_js_href("javascript:void(0)") is True, ""))
    cases.append(("javascript_upper", _is_js_href("JavaScript:goView(1)") is True, ""))
    cases.append(("javascript_leading_ws", _is_js_href("  javascript:x()") is True, ""))

    # Negative — 진짜 URL
    cases.append(("relative", _is_js_href("/view/123") is False, ""))
    cases.append(("absolute", _is_js_href("https://x.com/a") is False, ""))
    cases.append(("query_only", _is_js_href("?id=1") is False, ""))

    return cases
