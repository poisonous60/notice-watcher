"""probe.extract.detect_peertube_platform — PeerTube app-shell marker 판정."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import detect_peertube_platform

    cases: list[tuple[str, bool, str]] = []

    html_meta = (
        '<html><head><meta property="og:platform" content="PeerTube">'
        '<script>window.PeerTubeServerConfig = "{}"</script></head></html>'
    )
    out = detect_peertube_platform(html=html_meta, base_url="https://diode.zone/")
    cases.append(("og_platform_matches",
                  out is not None and out["is_peertube"] is True and out["base_url"] == "https://diode.zone",
                  f"got {out!r}"))

    html_title = "<html><head><title>Example PeerTube</title></head></html>"
    out = detect_peertube_platform(html=html_title, base_url="https://video.example/")
    cases.append(("title_matches",
                  out is not None and out["base_url"] == "https://video.example",
                  f"got {out!r}"))

    cases.append(("plain_no_match",
                  detect_peertube_platform(html="<html><title>Video</title></html>", base_url="https://example.com/") is None,
                  ""))
    cases.append(("empty_html_none",
                  detect_peertube_platform(html="", base_url="https://diode.zone/") is None,
                  ""))

    return cases
