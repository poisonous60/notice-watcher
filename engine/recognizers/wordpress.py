"""WordPress REST API -> generic httpx_json config.

Root/news URLs are not recognized by URL alone because WordPress powers many
non-board pages. `probe.extract.detect_wordpress_platform` detects REST API
markers in HTML and register.py dispatches here after probe.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlsplit

NAME = "wordpress"

_NOTE = ("WordPress REST API — probe 가 HTML 의 REST discovery marker 를 확인한 뒤 "
         "`/wp-json/wp/v2/<post_type>` JSON API 로 등록한다.")


def _api_base_from_url(url: str) -> Optional[str]:
    parts = urlsplit(url)
    host = (parts.netloc or "").strip().lower()
    if not host or "." not in host:
        return None
    path = parts.path or ""
    marker = "/wp-json"
    idx = path.lower().find(marker)
    if idx < 0:
        return None
    return f"{parts.scheme or 'https'}://{host}{path[:idx + len(marker)].rstrip('/')}"


def build_config(base_url: str, *, api_base: Optional[str] = None, post_type: str = "posts") -> Optional[dict]:
    api = (api_base or _api_base_from_url(base_url) or "").strip().rstrip("/")
    if not api:
        return None
    parts = urlsplit(api)
    host = (parts.netloc or "").strip().lower()
    if not host or "." not in host:
        return None
    ptype = (post_type or "posts").strip().strip("/") or "posts"
    endpoint = f"{api}/wp/v2/{ptype}"
    board = ptype
    return {
        "version": 1,
        "site": host,
        "board": board,
        "strategy": "httpx_json",
        "headers": {"Accept": "application/json"},
        "list": {
            "url_template": f"{endpoint}?per_page={{page_size}}&_embed",
            "pagination": {"kind": "query_param", "page_param": "page", "size_param": "per_page"},
            "page_size_max": 100,
            "list_path": [],
            "fields": {
                "post_id": [{"from": "json", "path": ["id"], "transform": [["to_str"]]}],
                "title": [
                    {"from": "json", "path": ["title", "rendered"],
                     "transform": [["html_unescape"], ["collapse_ws"]]},
                ],
                "url": [{"from": "json", "path": ["link"]}],
                "published_at": [
                    {"from": "json", "path": ["date_gmt"], "transform": [["append", "Z"]]},
                    {"from": "json", "path": ["date"]},
                ],
                "body": [{"from": "json", "path": ["content", "rendered"]}],
                "summary": [
                    {"from": "json", "path": ["excerpt", "rendered"],
                     "transform": [["html_unescape"], ["collapse_ws"]]},
                ],
            },
        },
        "article": {
            "url_template": f"{endpoint}/{{post_id}}?_embed",
            "fetch_kind": "json",
            "content": [{"from": "json", "path": ["content", "rendered"]}],
            "enrich": {
                "title": [
                    {"from": "json", "path": ["title", "rendered"],
                     "transform": [["html_unescape"], ["collapse_ws"]]},
                ],
                "published_at": [
                    {"from": "json", "path": ["date_gmt"], "transform": [["append", "Z"]]},
                    {"from": "json", "path": ["date"]},
                ],
            },
        },
        "_slug_board": f"{host}_{ptype}",
        "_source_url": endpoint,
        "_note": _NOTE,
    }


def _build(m: "re.Match", url: str) -> Optional[dict]:
    post_type = m.group("type") or "posts"
    return build_config(url, post_type=post_type)


PATTERNS = [
    (re.compile(r"^https?://[^/?#]+(?:/[^?#]*)?/wp-json/wp/v2/(?P<type>[A-Za-z0-9_-]+)(?:\?|$)", re.I), _build),
]
