"""probe.extract.detect_wordpress_platform — WordPress REST marker 판정."""
from __future__ import annotations

covers = ["detect_wordpress_platform"]


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import detect_wordpress_platform
    from engine.recognizers.wordpress import build_config
    from engine import validate_config

    cases: list[tuple[str, bool, str]] = []

    html_rest = """<html><head>
      <link rel="https://api.w.org/" href="https://example.com/wp-json/" />
      <meta name="generator" content="WordPress 6.5" />
      <link rel="stylesheet" href="/wp-content/themes/news/style.css" />
    </head><body></body></html>"""
    out = detect_wordpress_platform(html_rest, "https://example.com/news/")
    cases.append(("rest_link_detects", bool(out and out["api_base"] == "https://example.com/wp-json"), str(out)))
    if out:
        cfg = build_config("https://example.com/news/", api_base=out["api_base"], post_type="news")
        try:
            validate_config(cfg or {})
            cases.append(("news_config_valid", cfg is not None and cfg["list"]["list_path"] == [], ""))
        except Exception as e:  # noqa: BLE001
            cases.append(("news_config_valid", False, repr(e)))

    html_assets = """<html><head><meta name="generator" content="WordPress" />
      <script src="/wp-includes/js/jquery.js"></script>
      <link href="/wp-content/plugins/foo/style.css" rel="stylesheet"></head></html>"""
    out2 = detect_wordpress_platform(html_assets, "https://www.gkids.com/")
    cases.append(("generator_assets_detects", bool(out2 and out2["posts_endpoint"].endswith("/wp/v2/posts")), str(out2)))

    plain = "<html><head><title>News</title></head><body><a href='/news/1'>A</a></body></html>"
    cases.append(("plain_no_match", detect_wordpress_platform(plain, "https://example.org/news/") is None, ""))
    cases.append(("empty_html_none", detect_wordpress_platform("", "https://example.com/") is None, ""))
    cases.append(("empty_base_none", detect_wordpress_platform(html_rest, "") is None, ""))

    return cases
