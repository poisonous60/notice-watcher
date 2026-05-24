"""RSS/Atom feed URL discovery signals for config generation."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


covers = ["rss_feed_urls"]


def _har(entries: list[dict]) -> dict:
    return {"log": {"entries": entries}}


def _entry(url: str, content_type: str, text: str) -> dict:
    return {
        "request": {"url": url},
        "response": {
            "status": 200,
            "headers": [{"name": "content-type", "value": content_type}],
            "content": {"text": text},
        },
    }


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import rss_feed_urls, write_list_candidates

    cases: list[tuple[str, bool, str]] = []
    html = """
    <html><head>
      <link rel="alternate" type="application/rss+xml" href="/podcast/rss.xml">
      <link rel="alternate" type="application/atom+xml" href="https://example.com/atom.xml">
    </head><body>
      <a href="/shows/feed">feed</a>
      <a href="/plain">plain</a>
    </body></html>
    """
    with tempfile.TemporaryDirectory(prefix="test_rss_feed_urls_") as td:
        out_dir = Path(td)
        har_path = out_dir / "traffic.har"
        har_path.write_text(
            json.dumps(_har([
                _entry("https://example.com/api/notfeed.xml", "text/xml", "<urlset></urlset>"),
                _entry("https://example.com/live.xml", "text/xml; charset=utf-8", "<rss><channel/></rss>"),
            ])),
            encoding="utf-8",
        )

        urls = rss_feed_urls(html=html, base_url="https://example.com/podcast/", har_path=har_path)
        triples = {(u["url"], u["source"]) for u in urls}
        cases.append(("link_rel_rss_urljoined",
                      ("https://example.com/podcast/rss.xml", "link_rel") in triples,
                      f"got {urls!r}"))
        cases.append(("link_rel_atom_kept",
                      ("https://example.com/atom.xml", "link_rel") in triples,
                      f"got {urls!r}"))
        cases.append(("html_body_feed_anchor_urljoined",
                      ("https://example.com/shows/feed", "html_body") in triples,
                      f"got {urls!r}"))
        cases.append(("har_xml_feed_response_detected",
                      ("https://example.com/live.xml", "har_resp_xml") in triples,
                      f"got {urls!r}"))
        cases.append(("har_xml_sitemap_ignored",
                      not any(u["url"].endswith("notfeed.xml") for u in urls),
                      f"got {urls!r}"))

        write_list_candidates(
            out_dir,
            base_url="https://example.com/podcast/",
            page_html=html,
            har_path=har_path,
            html_candidates=[],
            json_api_candidates=[],
            hydration_candidates=[],
            first_article_url=None,
        )
        payload = json.loads((out_dir / "list_candidates.json").read_text(encoding="utf-8"))
        cases.append(("write_list_candidates_includes_rss_feed_urls",
                      payload.get("rss_feed_urls") == urls,
                      f"got {payload.get('rss_feed_urls')!r} expected {urls!r}"))

    return cases
