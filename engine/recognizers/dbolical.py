"""DBolical news boards (IndieDB/ModDB) -> RSS httpx_html config.

The public HTML news pages are Cloudflare-sensitive, but the DBolical RSS
hosts expose the same news board as stable RSS XML:

  - https://rss.indiedb.com/news/feed/rss.xml
  - https://rss.moddb.com/news/feed/rss.xml

Only the top-level /news board is recognized here. Game article URLs such as
/games/<game>/news/<slug> are individual articles and must not match.
"""
from __future__ import annotations

import re
from typing import Optional

NAME = "dbolical"

_HOSTS = ("indiedb", "moddb")
_HOST_ALT = "|".join(_HOSTS)

_RE_NEWS = re.compile(
    rf"//(?:www\.)?({_HOST_ALT})\.com/news/?(?:[?#].*)?$",
    re.I,
)
_RE_RSS = re.compile(
    rf"//rss\.({_HOST_ALT})\.com/news/feed/rss\.xml(?:[?#].*)?$",
    re.I,
)


def _build(m: "re.Match", url: str) -> Optional[dict]:
    host = m.group(1).lower()
    site = f"{host}.com"
    feed_url = f"https://rss.{site}/news/feed/rss.xml"
    return {
        "version": 1,
        "site": site,
        "board": "news",
        "_slug_board": f"{host}_news",
        "_source_url": feed_url,
        "strategy": "httpx_html",
        "headers": {
            "User-Agent": "notice-watcher/1.0 (+polite)",
            "Accept": "application/rss+xml, application/xml;q=0.9, text/html;q=0.8, */*;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
        },
        "timeout": 15,
        "polite_sleep": {"min": 5, "max": 5},
        "list": {
            "url_template": f"https://rss.{site}/news/feed/rss.xml",
            "pagination": {"kind": "none"},
            "row_selector": "channel > item",
            "fields": {
                "post_id": [
                    {"from": "css", "selector": "guid", "text": True, "transform": [["collapse_ws"]]},
                    {
                        "from": "css",
                        "selector": "link",
                        "text": True,
                        "transform": [["strip_query_fragment"], ["regex_extract", r"/news/([^/?#]+)/?$"]],
                    },
                ],
                "title": [
                    {"from": "css", "selector": "title", "text": True, "transform": [["collapse_ws"]]},
                ],
                "url": [
                    {
                        "from": "css",
                        "selector": "link",
                        "text": True,
                        "transform": [["collapse_ws"], ["strip_query_fragment"]],
                    },
                ],
                "published_at": [
                    {
                        "from": "css",
                        "selector": "pubDate",
                        "text": True,
                        "transform": [["collapse_ws"], ["iso8601", ["%a, %d %b %Y %H:%M:%S %z"]]],
                    },
                ],
                "summary": [
                    {"from": "css", "selector": "media|description", "text": True, "transform": [["collapse_ws"]]},
                    {
                        "from": "css",
                        "selector": "description",
                        "text": True,
                        "transform": [["html_unescape"], ["collapse_ws"]],
                    },
                ],
                "cover_image": [
                    {"from": "attr", "selector": "enclosure[url]", "attr": "url"},
                    {"from": "attr", "selector": "media|thumbnail[url]", "attr": "url"},
                ],
            },
        },
        "article": {
            "fetch_kind": "html",
            "skip_status": [403],
            "body_empty_acceptable": True,
            "content": [
                {"from": "css", "selector": "div#articlecontent", "html": True},
                {"from": "css", "selector": "article div.bodyarticle", "html": True},
                {"from": "css", "selector": "div.bodyarticle", "html": True},
            ],
            "enrich": {
                "title": [
                    {
                        "from": "css",
                        "selector": "span.heading[itemprop='headline']",
                        "text": True,
                        "transform": [["collapse_ws"]],
                    },
                    {"from": "css", "selector": "h1", "text": True, "transform": [["collapse_ws"]]},
                ],
                "published_at": [
                    {
                        "from": "css",
                        "selector": "time[itemprop='datePublished']",
                        "attr": "datetime",
                        "transform": [
                            [
                                "iso8601",
                                [
                                    "%Y-%m-%dT%H:%M:%S%z",
                                    "%Y-%m-%dT%H:%M:%S.%f%z",
                                    "%b %d, %Y",
                                ],
                            ]
                        ],
                    },
                ],
                "author": [
                    {
                        "from": "css",
                        "selector": "span[itemprop='author'] span[itemprop='name'] a",
                        "text": True,
                        "transform": [["collapse_ws"]],
                    },
                ],
            },
        },
        "_note": (
            f"DBolical {site} /news known-platform RSS. The submitted HTML board may be "
            f"Cloudflare-challenged, but rss.{site}/news/feed/rss.xml returns RSS items "
            "with guid/title/link/pubDate/description/enclosure. Article pages keep DBolical "
            "body selectors when accessible and skip 403 bodies."
        ),
    }


PATTERNS = [
    (_RE_RSS, _build),
    (_RE_NEWS, _build),
]
