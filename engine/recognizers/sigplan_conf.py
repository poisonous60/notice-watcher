"""SIGPLAN/researchr conference home pages -> httpx_html.

SIGPLAN conference sites such as pldi26.sigplan.org and popl26.sigplan.org use
researchr's Conf template. The home page exposes featured papers as
``a.highlight-carousel-item.navigate`` links to ``/details/.../<id>/...``.
Using the anchor itself as the row avoids duplicate post IDs from wider
carousel containers.
"""
from __future__ import annotations

import re
from typing import Optional

from ._common import UA

NAME = "sigplan_conf"

_RE = re.compile(r"^https?://([a-z0-9-]+)\.sigplan\.org/?(?:[?#].*)?$", re.I)


def _build(m: "re.Match", url: str) -> Optional[dict]:
    subdomain = m.group(1).lower()
    host = f"{subdomain}.sigplan.org"
    list_url = f"https://{host}/"
    return {
        "version": 1,
        "site": host,
        "board": "home",
        "strategy": "httpx_html",
        "_slug_board": "root",
        "headers": {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
            "Referer": list_url,
        },
        "timeout": 15,
        "polite_sleep": {"min": 2, "max": 4},
        "list": {
            "url_template": list_url,
            "pagination": {"kind": "none"},
            "row_selector": "a.highlight-carousel-item.navigate[href*='/details/']",
            "include_notices": True,
            "fields": {
                "post_id": [
                    {
                        "from": "attr",
                        "selector": ":self",
                        "attr": "href",
                        "transform": [["regex_extract", r"/details/[^/]+/(\d+)/"]],
                    }
                ],
                "title": [
                    {
                        "from": "css",
                        "selector": "h5",
                        "text": True,
                        "transform": [["collapse_ws"]],
                    }
                ],
                "url": [
                    {
                        "from": "attr",
                        "selector": ":self",
                        "attr": "href",
                        "transform": [["urljoin", list_url]],
                    }
                ],
                "author": [
                    {
                        "from": "css",
                        "selector": "h6 i",
                        "text": True,
                        "transform": [["collapse_ws"]],
                    },
                    {
                        "from": "attr",
                        "selector": "img[alt]",
                        "attr": "alt",
                        "transform": [["collapse_ws"]],
                    },
                ],
            },
        },
        "article": {
            "fetch_kind": "html",
            "content": [
                {"from": "css", "selector": "#content", "html": True},
                {"from": "css", "selector": "body", "html": True},
            ],
        },
        "_source_url": list_url,
        "_note": (
            f"SIGPLAN/researchr Conf home page ({host}) — featured papers are "
            "a.highlight-carousel-item.navigate rows. post_id is the numeric "
            "/details/.../<id>/ URL segment, avoiding duplicate IDs from wider "
            "carousel containers."
        ),
    }


PATTERNS = [
    (_RE, _build),
]
