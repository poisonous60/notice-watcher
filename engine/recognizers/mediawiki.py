"""MediaWiki RecentChanges pages -> httpx_html config.

Promotion source: eight existing Wikipedia/Wikimedia/Wiktionary RecentChanges
configs share the MediaWiki changes-list DOM:
`li.mw-changeslist-line` rows with `a.mw-changeslist-title` as the article link.
"""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Optional
from urllib.parse import quote, unquote

from ._common import UA

NAME = "mediawiki"

_RE = re.compile(
    r"^https?://([^/?#]+\.(?:wikipedia|wikimedia|wiktionary)\.org)"
    r"(?:/wiki/([^?#]+)|/w/index\.php\?([^#]*))",
    re.I,
)

_TITLE_BY_HOST = {
    "de.wikipedia.org": "Spezial:Letzte_%C3%84nderungen",
    "fr.wikipedia.org": "Sp%C3%A9cial:Modifications_r%C3%A9centes",
    "ja.wikipedia.org": "%E7%89%B9%E5%88%A5:%E6%9C%80%E8%BF%91%E3%81%AE%E6%9B%B4%E6%96%B0",
    "ko.wikipedia.org": "%ED%8A%B9%EC%88%98:%EC%B5%9C%EA%B7%BC%EB%B0%94%EB%80%9C",
    "zh.wikipedia.org": "Special:%E6%9C%80%E8%BF%91%E6%9B%B4%E6%94%B9",
    "commons.wikimedia.org": "Special:RecentChanges",
    "en.wikipedia.org": "Special:RecentChanges",
    "en.wiktionary.org": "Special:RecentChanges",
}

_RECENT_TITLES = {unquote(v) for v in _TITLE_BY_HOST.values()}


def _title_from_url(url: str, path_title: str | None, query: str | None) -> str | None:
    if path_title:
        return unquote(path_title)
    if query:
        for part in query.split("&"):
            key, sep, value = part.partition("=")
            if sep and key == "title":
                return unquote(value)
    return None


def _encoded_title_for(host: str, title: str) -> str:
    configured = _TITLE_BY_HOST.get(host)
    if configured and unquote(configured) == title:
        return configured
    return quote(title, safe=":")


def _build(m: "re.Match", url: str) -> Optional[dict]:
    host = m.group(1).lower()
    if host not in _TITLE_BY_HOST:
        return None

    title = _title_from_url(url, m.group(2), m.group(3))
    if title not in _RECENT_TITLES:
        return None

    encoded_title = _encoded_title_for(host, title)
    base_url = f"https://{host}"
    list_url = f"{base_url}/w/index.php?title={encoded_title}&limit=50"

    cfg = deepcopy(_BASE_CONFIG)
    cfg["site"] = host
    cfg["headers"]["Referer"] = f"{base_url}/wiki/{encoded_title}"
    cfg["list"]["url_template"] = list_url
    cfg["list"]["fields"]["url"][0]["transform"][0][1] = base_url
    cfg["_source_url"] = f"{base_url}/wiki/{encoded_title}"
    cfg["_note"] = (
        "MediaWiki Special:RecentChanges 자동 인식. li.mw-changeslist-line 행과 "
        "a.mw-changeslist-title 링크를 사용하며, /wiki/<localized Special> 및 "
        "/w/index.php?title=<localized Special> 형태만 매칭한다."
    )
    return cfg


_BASE_CONFIG = {
    "version": 1,
    "site": "",
    "board": "RecentChanges",
    "strategy": "httpx_html",
    "_slug_board": "RecentChanges",
    "headers": {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        "Upgrade-Insecure-Requests": "1",
        "Referer": "",
    },
    "timeout": 15,
    "polite_sleep": {"min": 5, "max": 6},
    "list": {
        "url_template": "",
        "pagination": {"kind": "none"},
        "row_selector": "li.mw-changeslist-line",
        "row_required_selector": "a.mw-changeslist-title",
        "include_notices": True,
        "fields": {
            "post_id": [
                {"from": "attr", "selector": ":self", "attr": "data-mw-revid", "transform": [["default", ""]]},
                {"from": "attr", "selector": ":self", "attr": "data-mw-logid", "transform": [["default", ""]]},
                {"from": "attr", "selector": ":self", "attr": "data-mw-ts", "transform": [["default", ""]]},
            ],
            "title": [
                {"from": "css", "selector": "a.mw-changeslist-title", "text": True, "transform": [["collapse_ws"]]},
                {"from": "attr", "selector": ":self", "attr": "data-target-page", "transform": [["collapse_ws"]]},
                {
                    "from": "attr",
                    "selector": "span.mw-changeslist-line-inner",
                    "attr": "data-target-page",
                    "transform": [["collapse_ws"]],
                },
            ],
            "url": [
                {
                    "from": "attr",
                    "selector": "a.mw-changeslist-title",
                    "attr": "href",
                    "transform": [["urljoin", ""]],
                }
            ],
            "published_at": [
                {
                    "from": "attr",
                    "selector": ":self",
                    "attr": "data-mw-ts",
                    "transform": [["iso8601", ["%Y%m%d%H%M%S"], "+00:00"]],
                }
            ],
            "author": [
                {
                    "from": "css",
                    "selector": "a.mw-userlink, a.mw-tempuserlink, .mw-userlink bdi",
                    "pick": "first_matching",
                    "match": ".+",
                    "text": True,
                    "transform": [["collapse_ws"]],
                }
            ],
            "category": [
                {
                    "from": "css",
                    "selector": "span.mw-tag-marker a, span.mw-tag-marker, span.mw-tag-markers a",
                    "pick": "first_matching",
                    "match": ".+",
                    "text": True,
                    "transform": [["collapse_ws"]],
                }
            ],
            "summary": [
                {"from": "css", "selector": "span.comment", "text": True, "transform": [["collapse_ws"]]}
            ],
        },
        "page_size_max": 50,
    },
    "article": {
        "fetch_kind": "html",
        "content": [
            {"from": "css", "selector": "div.mw-parser-output", "html": True},
            {"from": "css", "selector": "#mw-content-text .mw-parser-output", "html": True},
            {"from": "css", "selector": "#mw-content-text", "html": True},
        ],
        "enrich": {
            "title": [
                {"from": "css", "selector": "h1#firstHeading", "text": True, "transform": [["collapse_ws"]]},
                {"from": "css", "selector": "h1.firstHeading", "text": True, "transform": [["collapse_ws"]]},
            ]
        },
    },
}

PATTERNS = [
    (_RE, _build),
]
