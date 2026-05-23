"""Medium publication/tag RSS feeds -> httpx_html XML config.

Slug compatibility note: NAME intentionally mirrors the old fallback platform
(`host_medium-com`) so existing queued host_medium-com_* slugs stay stable.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlsplit

from ._common import UA

NAME = "host_medium-com"

_RE_FEED_TAG = re.compile(r"//medium\.com/feed/tag/([^/?#]+)/*(?:[?#].*)?$", re.I)
_RE_FEED_PUB = re.compile(r"//medium\.com/feed/([^/?#]+)/*(?:[?#].*)?$", re.I)
_RE_PUBLICATION = re.compile(r"//medium\.com/([^/?#@]+)/*(?:[?#].*)?$", re.I)
_RESERVED = {
    "about", "creators", "feed", "jobs", "m", "membership", "new-story", "p",
    "policy", "search", "tag", "tags", "topic", "topics",
}


def _config(*, board: str, source_url: str, slug_board: str, feed_url: str | None = None,
            site: str = "medium.com", referer: str = "https://medium.com/") -> dict:
    list_url = feed_url or "https://medium.com/feed/{board}"
    return {
        "version": 1,
        "site": site,
        "board": board,
        "strategy": "httpx_html",
        "_slug_board": slug_board,
        "_source_url": source_url,
        "headers": {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
            "Referer": referer,
        },
        "timeout": 15,
        "list": {
            "url_template": list_url,
            "pagination": {"kind": "none"},
            "row_selector": "channel > item",
            "fields": {
                "post_id": [
                    {
                        "from": "css",
                        "selector": "guid",
                        "text": True,
                        "transform": [["regex_extract", "/p/([0-9a-f]{10,})"]],
                    }
                ],
                "title": [
                    {
                        "from": "css",
                        "selector": "title",
                        "text": True,
                        "transform": [["collapse_ws"]],
                    }
                ],
                "url": [
                    {
                        "from": "css",
                        "selector": "link",
                        "text": True,
                        "transform": [["strip"]],
                    },
                    {"from": "template", "value": "https://medium.com/p/{post_id}"},
                ],
                "published_at": [
                    {
                        "from": "css",
                        "selector": "pubDate",
                        "text": True,
                        "transform": [["iso8601", ["%a, %d %b %Y %H:%M:%S GMT"], "Z"]],
                    }
                ],
                "summary": [
                    {
                        "from": "css",
                        "selector": "description",
                        "text": True,
                        "transform": [["html_unescape"], ["collapse_ws"]],
                    }
                ],
                "cover_image": [
                    {
                        "from": "css",
                        "selector": "description",
                        "text": True,
                        "transform": [
                            ["html_unescape"],
                            ["regex_extract", "<img[^>]+src=[\"']([^\"']+)"],
                        ],
                    }
                ],
            },
        },
        "article": {
            "fetch_kind": "html",
            "skip_status": [403],
            "content": [
                {"from": "css", "selector": "article section", "html": True},
                {"from": "css", "selector": "article", "html": True},
                {"from": "css", "selector": "body", "html": True},
            ],
            "body_empty_acceptable": True,
        },
        "_note": (
            "Medium RSS feed/publication recognizer. Medium pages expose RSS at "
            "/feed/<publication> or /feed/tag/<tag>; the httpx_html strategy parses "
            "RSS XML through parse_html_or_xml and extracts channel > item."
        ),
    }


def _build_feed_tag(m: "re.Match", url: str) -> Optional[dict]:
    tag = m.group(1)
    return _config(board=f"tag/{tag}", source_url=url, slug_board="feed")


def _build_feed_pub(m: "re.Match", url: str) -> Optional[dict]:
    pub = m.group(1)
    if pub.lower() in _RESERVED:
        return None
    return _config(board=pub, source_url=url, slug_board=pub)


def _build_publication(m: "re.Match", url: str) -> Optional[dict]:
    pub = m.group(1)
    if pub.lower() in _RESERVED:
        return None
    path = (urlsplit(url).path or "").strip("/")
    if "/" in path:
        return None
    return _config(board=pub, source_url=url, slug_board=pub)


def build_custom_domain_config(feed_url: str, *, base_url: str | None = None) -> Optional[dict]:
    parts = urlsplit(feed_url)
    host = (parts.netloc or "").strip().lower()
    if not host or "." not in host:
        return None
    if host == "medium.com" or host.endswith(".medium.com"):
        return None
    clean_feed = f"{parts.scheme or 'https'}://{host}{parts.path.rstrip('/') or '/feed'}"
    origin = base_url or f"{parts.scheme or 'https'}://{host}"
    return _config(
        board=host,
        source_url=clean_feed,
        slug_board=host,
        feed_url=clean_feed,
        site=host,
        referer=origin.rstrip("/") + "/",
    )


PATTERNS = [
    (_RE_FEED_TAG, _build_feed_tag),
    (_RE_FEED_PUB, _build_feed_pub),
    (_RE_PUBLICATION, _build_publication),
]
