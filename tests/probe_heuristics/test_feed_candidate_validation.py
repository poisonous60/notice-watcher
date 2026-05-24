"""feed_candidates validation keeps path guesses from passing board gates."""
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
    from scripts.register import _count_board_feed_signals, _has_verified_feed

    cases: list[tuple[str, bool, str]] = []

    old_fetch = discover._fetch_feed_candidate_response
    old_url_serves_feed = discover._url_serves_feed
    fetch_counts: dict[str, int] = {}

    rss_ok = '<rss version="2.0"><channel><item><title>A</title></item><item><title>B</title></item></channel></rss>'
    rss_empty = '<rss version="2.0"><channel><title>empty</title></channel></rss>'
    atom_ok = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>A</title></entry></feed>'
    html_spa = '<!doctype html><html><head><title>app</title></head><body><div id="app"></div></body></html>'

    responses = {
        "https://example.com/rss": _Resp(200, "application/rss+xml", rss_ok),
        "https://example.com/empty.xml": _Resp(200, "application/rss+xml", rss_empty),
        "https://example.com/feed": _Resp(200, "text/html; charset=utf-8", html_spa),
        "https://example.com/atom": _Resp(200, "application/atom+xml", atom_ok),
        "https://www.cbsnews.com/podcasts/rss": _Resp(200, "application/rss+xml", rss_empty),
        "https://www.dotnetrocks.com/RSS": _Resp(200, "text/html; charset=utf-8", html_spa),
        "https://feeds.thisamericanlife.org/talpodcast": _Resp(200, "application/rss+xml", rss_ok),
        "https://oxide.computer/podcast/rss.xml": _Resp(200, "application/rss+xml", rss_ok),
    }

    def fake_fetch(url: str, *, timeout: float = 10.0):
        fetch_counts[url] = fetch_counts.get(url, 0) + 1
        if url == "https://example.com/down.xml":
            raise RuntimeError("boom")
        return responses[url]

    discover._fetch_feed_candidate_response = fake_fetch
    try:
        ok = discover.validate_feed_candidate("https://example.com/rss", source="well-known-path")
        cases.append(("rss_with_items_valid",
                      ok.get("validated") is True and ok.get("root_tag") == "rss" and ok.get("item_count") == 2,
                      f"got {ok!r}"))

        empty = discover.validate_feed_candidate("https://example.com/empty.xml", source="well-known-path")
        cases.append(("empty_rss_invalid",
                      empty.get("validated") is False and empty.get("root_tag") == "rss" and empty.get("item_count") == 0,
                      f"got {empty!r}"))

        spa = discover.validate_feed_candidate("https://example.com/feed", source="input-url-feed-path")
        cases.append(("html_spa_invalid",
                      spa.get("validated") is False and spa.get("root_tag") == "html" and spa.get("item_count") is None,
                      f"got {spa!r}"))

        atom = discover.validate_feed_candidate("https://example.com/atom", source="well-known-path")
        cases.append(("atom_entry_valid",
                      atom.get("validated") is True and atom.get("root_tag") == "feed" and atom.get("item_count") == 1,
                      f"got {atom!r}"))

        large_rss = "<rss><channel>" + "".join("<item><title>x</title></item>" for _ in range(50_000)) + "</channel></rss>"
        root_tag, item_count = discover._xml_root_and_item_count(large_rss)
        cases.append(("large_feed_parse_is_capped_but_counted",
                      root_tag == "rss" and isinstance(item_count, int) and item_count > 0,
                      f"got {(root_tag, item_count)!r}"))

        cbs = discover.validate_feed_candidate("https://www.cbsnews.com/podcasts/rss", source="well-known-path")
        cases.append(("cbs_empty_feed_fixture_invalid",
                      cbs.get("validated") is False and cbs.get("root_tag") == "rss" and cbs.get("item_count") == 0,
                      f"got {cbs!r}"))

        fetch_counts.clear()
        verified_cbs = discover._verified_feed_candidate(
            "https://www.cbsnews.com/podcasts/rss",
            source="input-url-feed-fetch",
        )
        cases.append(("verified_candidate_rejects_validate_failure",
                      verified_cbs is None,
                      f"got {verified_cbs!r}"))
        cases.append(("verified_candidate_fetches_once",
                      fetch_counts.get("https://www.cbsnews.com/podcasts/rss") == 1,
                      f"got counts {fetch_counts!r}"))

        dotnetrocks = discover.validate_feed_candidate("https://www.dotnetrocks.com/RSS", source="input-url-feed-path")
        cases.append(("dotnetrocks_html_spa_fixture_invalid",
                      dotnetrocks.get("validated") is False and dotnetrocks.get("root_tag") == "html",
                      f"got {dotnetrocks!r}"))

        tal = discover.validate_feed_candidate("https://feeds.thisamericanlife.org/talpodcast", source="input-url-feed-fetch")
        cases.append(("thisamericanlife_feed_fixture_valid",
                      tal.get("validated") is True and tal.get("item_count") == 2,
                      f"got {tal!r}"))

        oxide = discover.validate_feed_candidate("https://oxide.computer/podcast/rss.xml", source="well-known-path")
        cases.append(("oxide_feed_fixture_valid",
                      oxide.get("validated") is True and oxide.get("item_count") == 2,
                      f"got {oxide!r}"))

        err = discover.validate_feed_candidate("https://example.com/down.xml", source="well-known-path")
        cases.append(("fetch_error_invalid",
                      err.get("validated") is False and err.get("content_type") is None and err.get("root_tag") is None,
                      f"got {err!r}"))

        digest = {"feed_candidates": [empty, spa]}
        cases.append(("invalid_candidates_do_not_count_for_board_shape",
                      _count_board_feed_signals(digest, {}) == 0 and _has_verified_feed(digest) is False,
                      f"got digest {digest!r}"))

        legacy_xml = {"source": "input-url-feed-fetch", "status": 200, "content_type": "application/xml"}
        legacy_digest = {"feed_candidates": [legacy_xml]}
        cases.append(("legacy_unvalidated_xml_candidate_does_not_count",
                      _count_board_feed_signals(legacy_digest, {}) == 0
                      and _has_verified_feed(legacy_digest) is False,
                      f"got digest {legacy_digest!r}"))

        digest_valid = {"feed_candidates": [ok]}
        cases.append(("validated_candidates_count_for_board_shape",
                      _count_board_feed_signals(digest_valid, {}) == 1 and _has_verified_feed(digest_valid) is True,
                      f"got digest {digest_valid!r}"))

        with tempfile.TemporaryDirectory() as td:
            html = '<html><head><link rel="alternate" type="application/rss+xml" href="/empty.xml"></head></html>'
            out = discover.discover_feeds(
                page_url="https://example.com/feed",
                page_html=html,
                out_dir=Path(td),
                timeout=0.01,
            )
            by_url = {c.get("url"): c for c in out.get("candidates", [])}
            cases.append(("discover_keeps_invalid_path_candidate_with_metadata",
                          by_url["https://example.com/feed"].get("validated") is False
                          and by_url["https://example.com/feed"].get("root_tag") == "html",
                          f"got {out!r}"))
            cases.append(("discover_validates_head_alternate",
                          by_url["https://example.com/empty.xml"].get("validated") is False
                          and by_url["https://example.com/empty.xml"].get("item_count") == 0,
                          f"got {out!r}"))
    finally:
        discover._fetch_feed_candidate_response = old_fetch
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
