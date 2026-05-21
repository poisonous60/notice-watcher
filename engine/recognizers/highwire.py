"""HighWire Press 기반 bioRxiv/medRxiv recent 목록 fast-path.

승급 출처: N100 snapshot 의 bioRxiv/medRxiv 개별 config 2건
(`.../content/early/recent`). 두 사이트 모두 HighWire DOM 을 쓰지만, snapshot 의
list/article selector 와 date timezone 이 다르므로 host 별 canonical skeleton 을 유지한다.
"""
from __future__ import annotations

import re
from typing import Optional

from ._common import UA

NAME = "highwire"

_RE = re.compile(r"//(?:www\.)?(bio|med)rxiv\.org/content/early/recent/?(?:[?#].*)?$", re.I)


def _build(m: "re.Match", url: str) -> Optional[dict]:
    kind = m.group(1).lower()
    if kind == "bio":
        return _build_biorxiv()
    if kind == "med":
        return _build_medrxiv()
    return None


def _build_biorxiv() -> dict:
    source_url = "https://www.biorxiv.org/content/early/recent"
    return {
        "version": 1,
        "site": "biorxiv.org",
        "board": "biochemistry",
        "strategy": "httpx_html",
        "_slug_board": "content",
        "headers": {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": source_url,
            "Upgrade-Insecure-Requests": "1",
            "sec-ch-ua": "\"Chromium\";v=\"147\", \"Not.A/Brand\";v=\"8\"",
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": "\"Windows\"",
        },
        "timeout": 15,
        "list": {
            "url_template": "https://www.biorxiv.org/collection/{board}",
            "pagination": {"kind": "query_param", "page_param": "page"},
            "row_selector": "div.highwire-list-wrapper.highwire-article-citation-list div.highwire-article-citation.highwire-citation-type-highwire-article",
            "row_required_selector": "a.highwire-cite-linked-title",
            "include_notices": True,
            "fields": {
                "post_id": [{"from": "attr", "selector": ":self", "attr": "data-node-nid"}],
                "title": [{
                    "from": "css",
                    "selector": "a.highwire-cite-linked-title span.highwire-cite-title",
                    "text": True,
                    "transform": [["collapse_ws"]],
                }],
                "url": [{
                    "from": "attr",
                    "selector": "a.highwire-cite-linked-title",
                    "attr": "href",
                    "transform": [["urljoin", "https://www.biorxiv.org"]],
                }],
                "author": [{
                    "from": "css",
                    "selector": "span.highwire-citation-author",
                    "text": True,
                    "transform": [["collapse_ws"]],
                }],
                "category": [{"from": "const", "value": "Biochemistry"}],
                "published_at": [{
                    "from": "css",
                    "selector": "h3.highwire-list-title",
                    "text": True,
                    "transform": [["collapse_ws"], ["iso8601", ["%B %d, %Y"], "+00:00"]],
                }],
                "summary": [{
                    "from": "css",
                    "selector": "div.highwire-cite-metadata",
                    "text": True,
                    "transform": [["collapse_ws"]],
                }],
            },
        },
        "article": {
            "fetch_kind": "html",
            "content": [
                {"from": "css", "selector": "div.section.abstract", "html": True},
                {"from": "css", "selector": "div.abstract", "html": True},
                {"from": "css", "selector": "div#block-system-main .section", "html": True},
                {"from": "css", "selector": "div#block-system-main article", "html": True},
            ],
            "enrich": {
                "title": [{
                    "from": "css",
                    "selector": "h1#page-title",
                    "text": True,
                    "transform": [["collapse_ws"]],
                }],
                "published_at": [
                    {
                        "from": "css",
                        "selector": "meta[name='citation_date']",
                        "attr": "content",
                        "transform": [["date_only_to_iso", "+00:00"]],
                    },
                    {
                        "from": "css",
                        "selector": "meta[name='DC.Date']",
                        "attr": "content",
                        "transform": [["date_only_to_iso", "+00:00"]],
                    },
                ],
            },
        },
        "_source_url": source_url,
        "_note": ("HighWire Press bioRxiv recent 목록 — source URL 은 /content/early/recent 이지만 "
                  "snapshot list URL 은 /collection/{board} (board=biochemistry) 로 생성됨. "
                  "row div.highwire-article-citation, title a.highwire-cite-linked-title span.highwire-cite-title."),
    }


def _build_medrxiv() -> dict:
    source_url = "https://www.medrxiv.org/content/early/recent"
    return {
        "version": 1,
        "site": "medrxiv.org",
        "board": "all",
        "strategy": "httpx_html",
        "_slug_board": "content",
        "headers": {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": source_url,
        },
        "timeout": 30,
        "polite_sleep": {"min": 7, "max": 9},
        "list": {
            "url_template": source_url,
            "pagination": {"kind": "query_param", "page_param": "page"},
            "row_selector": "div.highwire-list-wrapper.highwire-article-citation-list > div.highwire-list > ul > li",
            "row_required_selector": "a.highwire-cite-linked-title",
            "fields": {
                "post_id": [{
                    "from": "attr",
                    "selector": "div.highwire-article-citation",
                    "attr": "data-pisa-master",
                    "transform": [["regex_extract", "^medrxiv;(.+)$"]],
                }],
                "title": [{
                    "from": "css",
                    "selector": "a.highwire-cite-linked-title span.highwire-cite-title",
                    "text": True,
                    "transform": [["collapse_ws"], ["strip"]],
                }],
                "url": [{
                    "from": "attr",
                    "selector": "a.highwire-cite-linked-title",
                    "attr": "href",
                    "transform": [["urljoin", "https://www.medrxiv.org"]],
                }],
                "published_at": [{
                    "from": "attr",
                    "selector": "div.highwire-article-citation",
                    "attr": "data-pisa",
                    "transform": [
                        ["regex_extract", r"^medrxiv;(\d{4}\.\d{2}\.\d{2})\."],
                        ["replace", ".", "-"],
                        ["date_only_to_iso", "+09:00"],
                    ],
                }],
                "author": [{
                    "from": "css",
                    "selector": "span.highwire-citation-author.first",
                    "text": True,
                    "transform": [["collapse_ws"]],
                }],
                "summary": [{
                    "from": "css",
                    "selector": "div.highwire-cite-metadata span.highwire-cite-metadata-doi",
                    "text": True,
                    "transform": [["collapse_ws"]],
                }],
            },
        },
        "article": {
            "fetch_kind": "html",
            "content": [
                {"from": "css", "selector": "div.section-abstract", "html": True},
                {"from": "css", "selector": "div#block-system-main .section.abstract", "html": True},
                {"from": "css", "selector": "div#block-system-main", "html": True},
            ],
            "enrich": {
                "title": [{
                    "from": "css",
                    "selector": "h1#page-title",
                    "text": True,
                    "transform": [["collapse_ws"]],
                }],
                "published_at": [{
                    "from": "css",
                    "selector": "div.highwire-cite-metadata span.highwire-cite-metadata-pages",
                    "text": True,
                    "transform": [
                        ["regex_extract", r"^(\d{4}\.\d{2}\.\d{2})"],
                        ["replace", ".", "-"],
                        ["date_only_to_iso", "+09:00"],
                    ],
                }],
            },
        },
        "_source_url": source_url,
        "_note": ("HighWire Press medRxiv recent 목록 — /content/early/recent 만 인식. "
                  "row li > div.highwire-article-citation, title a.highwire-cite-linked-title span.highwire-cite-title."),
    }


PATTERNS = [
    (_RE, _build),
]
