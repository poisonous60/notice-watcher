"""Substack publication RSS feeds -> httpx_html XML config."""
from __future__ import annotations

import re
from typing import Optional

from ._common import UA

NAME = "host_substack-com"

_RE_PUBLICATION = re.compile(
    r"//([a-z0-9-]+)\.substack\.com/?(?:archive)?/?(?:[?#].*)?$",
    re.I,
)
_RE_FEED = re.compile(
    r"//([a-z0-9-]+)\.substack\.com/feed/?(?:[?#].*)?$",
    re.I,
)
_RESERVED = {"www", "support", "on", "app", "api"}


def _config(*, subdomain: str, source_url: str) -> dict:
    host = f"{subdomain}.substack.com"
    feed_url = f"https://{host}/feed"
    return {
        "version": 1,
        "site": host,
        "board": subdomain,
        "strategy": "httpx_html",
        "_slug_board": subdomain,
        "_source_url": source_url,
        "headers": {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
            "Referer": f"https://{host}/",
        },
        "timeout": 15,
        "list": {
            "url_template": feed_url,
            "pagination": {"kind": "none"},
            "row_selector": "channel > item",
            "fields": {
                "post_id": [
                    {"from": "css", "selector": "guid", "text": True, "transform": [["strip"]]},
                    {"from": "css", "selector": "link", "text": True, "transform": [["strip"]]},
                ],
                "title": [
                    {"from": "css", "selector": "title", "text": True, "transform": [["collapse_ws"]]},
                ],
                "url": [
                    {"from": "css", "selector": "link", "text": True, "transform": [["strip"]]},
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
                {"from": "css", "selector": "article", "html": True},
                {"from": "css", "selector": ".available-content", "html": True},
                {"from": "css", "selector": "body", "html": True},
            ],
            "body_empty_acceptable": True,
        },
        "_note": (
            "Substack RSS recognizer. Publication roots and /archive pages expose "
            "recent posts at /feed; httpx_html parses the RSS XML and extracts channel > item."
        ),
    }


def _build(m: "re.Match", url: str) -> Optional[dict]:
    subdomain = m.group(1).lower()
    if subdomain in _RESERVED:
        return None
    return _config(subdomain=subdomain, source_url=url)


PATTERNS = [
    (_RE_FEED, _build),
    (_RE_PUBLICATION, _build),
]
