"""probe.extract.detect_mbin_platform — Mbin/kbin marker 판정."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import detect_mbin_platform

    cases: list[tuple[str, bool, str]] = []

    html_mbin = (
        '<html><head><meta name="keywords" content="mbin, content aggregator, fediverse"></head>'
        '<body data-controller="mbin notifications"><a href="/threads">Threads</a>'
        '<a href="/microblog">Microblog</a><a href="/magazines">Magazines</a></body></html>'
    )
    out = detect_mbin_platform(html=html_mbin, base_url="https://fedia.io/")
    cases.append(("data_controller_matches",
                  out is not None and out["is_mbin"] is True and out["base_url"] == "https://fedia.io",
                  f"got {out!r}"))

    out = detect_mbin_platform(html=html_mbin, base_url="https://fedia.io/m/news")
    cases.append(("magazine_path_captured",
                  out is not None and out.get("magazine_name") == "news",
                  f"got {out!r}"))

    cases.append(("plain_no_match",
                  detect_mbin_platform(html="<html><title>Forum</title></html>", base_url="https://example.com/") is None,
                  ""))
    cases.append(("empty_html_none",
                  detect_mbin_platform(html="", base_url="https://fedia.io/") is None,
                  ""))

    return cases
