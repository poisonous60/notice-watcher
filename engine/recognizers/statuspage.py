"""Statuspage.io history feeds -> Atom/RSS httpx_html config.

Direct feed URLs are distinctive enough to recognize safely:
  - https://<host>/history.atom
  - https://<host>/history.rss

Root status pages are not matched from URL alone; many unrelated sites can look
like a root landing page. If a root page exposes a feed, hand config can point at
the feed URL while this recognizer covers users who submit the feed directly.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

NAME = "statuspage"

_NOTE = ("Statuspage.io history feed — direct `/history.atom` 또는 `/history.rss` URL 을 "
         "httpx_html(XML) 로 수집 (entry/item id, title, published/pubDate, link).")


def build_config(feed_url: str) -> dict | None:
    parts = urlsplit(feed_url)
    host = (parts.netloc or "").strip().lower()
    path = parts.path or ""
    if not host or "." not in host:
        return None
    base = f"{parts.scheme or 'https'}://{host}"
    is_rss = path.lower().endswith("/history.rss")
    source_url = f"{base}/history.rss" if is_rss else f"{base}/history.atom"
    if is_rss:
        row_selector = "channel > item"
        fields = {
            "post_id": [
                {"from": "css", "selector": "guid", "text": True,
                 "transform": [["collapse_ws"], ["strip"]]},
            ],
            "title": [
                {"from": "css", "selector": "title", "text": True,
                 "transform": [["collapse_ws"]]},
            ],
            "url": [
                {"from": "css", "selector": "link", "text": True,
                 "transform": [["collapse_ws"], ["strip"]]},
            ],
            "published_at": [
                {"from": "css", "selector": "pubDate", "text": True,
                 "transform": [["collapse_ws"], ["iso8601", ["%a, %d %b %Y %H:%M:%S %z"]]]},
            ],
            "summary": [
                {"from": "css", "selector": "description", "text": True,
                 "transform": [["collapse_ws"]]},
            ],
        }
    else:
        row_selector = "entry"
        fields = {
            "post_id": [
                {"from": "css", "selector": "id", "text": True,
                 "transform": [["collapse_ws"], ["strip"]]},
            ],
            "title": [
                {"from": "css", "selector": "title", "text": True,
                 "transform": [["collapse_ws"]]},
            ],
            "url": [
                {"from": "attr", "selector": "link[rel=\"alternate\"]", "attr": "href",
                 "transform": [["collapse_ws"], ["strip"]]},
            ],
            "published_at": [
                {"from": "css", "selector": "published", "text": True,
                 "transform": [["collapse_ws"], ["iso8601", ["%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"]]]},
            ],
            "summary": [
                {"from": "css", "selector": "content", "text": True,
                 "transform": [["collapse_ws"]]},
            ],
        }
    return {
        "version": 1,
        "site": host,
        "board": "history",
        "strategy": "httpx_html",
        "list": {
            "url_template": source_url,
            "pagination": {"kind": "none"},
            "row_selector": row_selector,
            "include_notices": True,
            "fields": fields,
        },
        "article": {
            "fetch_kind": "html",
            "content": [
                {"from": "css", "selector": ".prose", "html": True},
                {"from": "css", "selector": "main", "html": True},
            ],
            "body_empty_acceptable": True,
        },
        "_slug_board": host,
        "_source_url": source_url,
        "_note": _NOTE,
    }


def _build(m: "re.Match", url: str) -> dict | None:
    return build_config(url)


_HISTORY_FEED_RE = re.compile(r"^https?://[^/?#]+/history\.(?:atom|rss)(?:\?|#|$)", re.I)

PATTERNS = [
    (_HISTORY_FEED_RE, _build),
]
