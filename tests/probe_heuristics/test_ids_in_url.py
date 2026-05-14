"""probe.extract._ids_in_url — URL path+query 에서 4자리+ 숫자 런 추출."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import _ids_in_url

    cases: list[tuple[str, bool, str]] = []

    out = _ids_in_url("https://x.com/view/12345")
    cases.append(("path_5digit", out == {"12345"}, f"got {out!r}"))

    out = _ids_in_url("https://x.com/view/123")
    cases.append(("path_3digit_excluded", out == set(), f"got {out!r}"))

    out = _ids_in_url("https://x.com/view/1234?ref=5678")
    cases.append(("path_and_query", out == {"1234", "5678"}, f"got {out!r}"))

    out = _ids_in_url("")
    cases.append(("empty", out == set(), f"got {out!r}"))

    out = _ids_in_url("https://x.com/about")
    cases.append(("no_digits", out == set(), f"got {out!r}"))

    return cases
