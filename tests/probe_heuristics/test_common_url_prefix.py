"""probe.extract._common_url_prefix — 공통 접두 문자열."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import _common_url_prefix

    cases: list[tuple[str, bool, str]] = []

    out = _common_url_prefix(["/view/1", "/view/2", "/view/3"])
    cases.append(("typical", out == "/view/", f"got {out!r}"))

    out = _common_url_prefix(["/view/1"])
    cases.append(("single_item", out == "/view/1", f"got {out!r}"))

    out = _common_url_prefix([])
    cases.append(("empty_list", out is None, f"got {out!r}"))

    out = _common_url_prefix(["/a", "/b"])
    cases.append(("only_slash", out == "/", f"got {out!r}"))

    out = _common_url_prefix(["abc", "xyz"])
    cases.append(("no_common", out is None, f"got {out!r}"))

    out = _common_url_prefix(["https://x.com/view/1", "https://x.com/view/2"])
    cases.append(("absolute_urls", out == "https://x.com/view/", f"got {out!r}"))

    return cases
