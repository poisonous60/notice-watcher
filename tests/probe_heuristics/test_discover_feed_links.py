"""probe.discover.discover_feeds — page-local feed links and path fallbacks."""
from __future__ import annotations

import tempfile
from pathlib import Path


def run() -> list[tuple[str, bool, str]]:
    import probe.discover as discover

    cases: list[tuple[str, bool, str]] = []

    old_url_serves_feed = discover._url_serves_feed

    def fake_url_serves_feed(url: str, *, timeout: float = 10.0) -> bool:
        return url in {
            "https://www.filecoin.io/blog/rss.xml",
            "https://www.filecoin.io/blog/feed",
        }

    discover._url_serves_feed = fake_url_serves_feed
    try:
        with tempfile.TemporaryDirectory() as td:
            html = """
            <html><body>
              <main>
                <a href="/blog/rss.xml">RSS</a>
                <a href="/blog/archive">Archive</a>
              </main>
            </body></html>
            """
            out = discover.discover_feeds(
                page_url="https://www.filecoin.io/blog",
                page_html=html,
                out_dir=Path(td),
                timeout=0.01,
            )
            urls = {c.get("url") for c in out.get("candidates", [])}
            sources = {c.get("source") for c in out.get("candidates", [])}
            cases.append(("visible_anchor_rss_xml_verified",
                          "https://www.filecoin.io/blog/rss.xml" in urls,
                          f"got {out!r}"))
            cases.append(("path_relative_feed_verified",
                          "https://www.filecoin.io/blog/feed" in urls,
                          f"got {out!r}"))
            cases.append(("candidate_sources_named",
                          {"page-feed-link", "page-path-fallback"}.issubset(sources),
                          f"got {sources!r}"))
    finally:
        discover._url_serves_feed = old_url_serves_feed

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
