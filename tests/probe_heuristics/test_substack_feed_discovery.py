"""probe.discover.discover_feeds - short well-known /feed validation for RSS hubs."""
from __future__ import annotations

import tempfile
from pathlib import Path


class _Resp:
    def __init__(self, status_code: int, content_type: str, text: str):
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.text = text


def run() -> list[tuple[str, bool, str]]:
    import probe.discover as discover

    cases: list[tuple[str, bool, str]] = []
    old_fetch = discover._fetch_feed_candidate_response
    calls: list[tuple[str, float]] = []

    rss_ok = '<rss version="2.0"><channel><item><title>A</title></item></channel></rss>'

    def fake_fetch(url: str, *, timeout: float = 10.0):
        calls.append((url, timeout))
        if url == "https://example.substack.com/feed":
            return _Resp(200, "application/rss+xml", rss_ok)
        return _Resp(404, "text/html; charset=utf-8", "<html>not found</html>")

    discover._fetch_feed_candidate_response = fake_fetch
    try:
        with tempfile.TemporaryDirectory() as td:
            out = discover.discover_feeds(
                page_url="https://example.substack.com/archive",
                page_html="<html><body><div id='app'></div></body></html>",
                out_dir=Path(td),
                timeout=10.0,
            )
        by_url = {c.get("url"): c for c in out.get("candidates", [])}
        feed = by_url.get("https://example.substack.com/feed")
        cases.append((
            "well_known_feed_validated",
            isinstance(feed, dict)
            and feed.get("validated") is True
            and feed.get("source") == "well-known-path"
            and feed.get("item_count") == 1,
            f"got {out!r}",
        ))
        feed_calls = [timeout for url, timeout in calls if url == "https://example.substack.com/feed"]
        cases.append((
            "well_known_feed_uses_short_timeout",
            feed_calls == [3.0],
            f"got calls {calls!r}",
        ))
    finally:
        discover._fetch_feed_candidate_response = old_fetch

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
