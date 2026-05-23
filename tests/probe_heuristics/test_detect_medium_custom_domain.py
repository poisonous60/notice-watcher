"""probe.extract.detect_medium_custom_domain — Medium custom domain RSS detection."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import detect_medium_custom_domain

    cases: list[tuple[str, bool, str]] = []

    html = """
    <html><head>
      <meta property="al:android:package" content="com.medium.reader">
      <meta property="al:ios:app_name" content="Medium">
      <link rel="alternate" type="application/rss+xml"
            href="https://blog.celo.org/feed?source=rss----abc">
    </head><body>
      <a href="https://medium.com/p/abcdef123456">canonical</a>
    </body></html>
    """
    out = detect_medium_custom_domain(html=html, base_url="https://blog.celo.org/")
    cases.append(("celo_medium_markers_match",
                  out is not None and out.get("is_medium_custom") is True
                  and out.get("base_url") == "https://blog.celo.org"
                  and out.get("feed_url") == "https://blog.celo.org/feed",
                  f"got {out!r}"))

    html_no_feed = """
    <html><head>
      <meta property="al:ios:app_name" content="Medium">
    </head><body>
      <a href="https://medium.com/p/abcdef123456">canonical</a>
    </body></html>
    """
    out = detect_medium_custom_domain(html=html_no_feed, base_url="https://blog.example/")
    cases.append(("medium_markers_default_to_feed",
                  out is not None and out.get("feed_url") == "https://blog.example/feed",
                  f"got {out!r}"))

    plain = '<html><head><link rel="alternate" type="application/rss+xml" href="/feed"></head></html>'
    out = detect_medium_custom_domain(html=plain, base_url="https://example.com/")
    cases.append(("plain_rss_not_medium", out is None, f"got {out!r}"))

    out = detect_medium_custom_domain(html=html, base_url="https://medium.com/foo")
    cases.append(("medium_dot_com_not_custom_domain", out is None, f"got {out!r}"))

    return cases


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    results = run()
    failed = [(n, d) for n, ok, d in results if not ok]
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {d}")
    if failed:
        print(f"\n{len(failed)} FAILED")
        sys.exit(1)
    print(f"\n{len(results)} passed")
