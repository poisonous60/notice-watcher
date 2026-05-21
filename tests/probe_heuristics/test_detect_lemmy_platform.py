"""probe.extract.detect_lemmy_platform — Lemmy SSR/app-shell marker 판정."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import detect_lemmy_platform

    cases: list[tuple[str, bool, str]] = []

    html_iso = (
        '<html><head><title>Lemmy</title></head><body>'
        '<script>window.isoData = {"site_res":{"site_view":{"local_site":{},'
        '"site":{"name":"Lemmy"}}},"version":"0.19.18"};</script>'
        '<a href="https://join-lemmy.org/docs/en/index.html">Docs</a>'
        '</body></html>'
    )
    out = detect_lemmy_platform(html=html_iso, base_url="https://lemmy.ml/")
    cases.append(("isodata_matches",
                  out is not None and out["is_lemmy"] is True and out["base_url"] == "https://lemmy.ml",
                  f"got {out!r}"))

    html_interstitial = (
        '<html><head><title>Making sure you are not a bot!</title>'
        '<meta property="og:title" content="Lemmy - A community of privacy and FOSS enthusiasts">'
        '</head><body>challenge</body></html>'
    )
    out = detect_lemmy_platform(html=html_interstitial, base_url="https://lemmy.ml/")
    cases.append(("anubis_og_title_matches",
                  out is not None and out["base_url"] == "https://lemmy.ml",
                  f"got {out!r}"))

    html_discourse = '<meta name="generator" content="Discourse 2026.5.0">'
    cases.append(("discourse_no_match",
                  detect_lemmy_platform(html=html_discourse, base_url="https://forum.openwrt.org/") is None,
                  ""))

    html_plain = '<html><head><meta property="og:title" content="Example"></head></html>'
    cases.append(("plain_no_match",
                  detect_lemmy_platform(html=html_plain, base_url="https://example.com/") is None,
                  ""))

    cases.append(("empty_html_none",
                  detect_lemmy_platform(html="", base_url="https://lemmy.ml/") is None,
                  ""))
    cases.append(("empty_base_none",
                  detect_lemmy_platform(html=html_iso, base_url="") is None,
                  ""))

    return cases
