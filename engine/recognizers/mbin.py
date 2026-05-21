"""Mbin/kbin threadiverse aggregators -> public entries JSON API."""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlsplit

from ._common import UA

NAME = "mbin"

_NOTE = (
    "Mbin/kbin aggregator — known-platform 자동 인식. `/api/entries?sort=newest&perPage=...` "
    "JSON API 를 httpx_json 으로 수집한다. API 가 401/anti-bot 으로 막힌 instance 는 "
    "known-platform fetch 검증에서 폴백한다."
)


def build_config(base_url: str) -> Optional[dict]:
    parts = urlsplit(base_url)
    host = (parts.netloc or "").strip().lower()
    if not host or "." not in host:
        return None
    base = f"{parts.scheme or 'https'}://{host}"
    return {
        "version": 1,
        "site": host,
        "board": "entries",
        "strategy": "httpx_json",
        "headers": {
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": base + "/",
        },
        "timeout": 15,
        "list": {
            "url_template": base + "/api/entries?sort=newest&perPage={page_size}",
            "pagination": {"kind": "query_param", "page_param": "p", "size_param": "perPage"},
            "page_size_max": 50,
            "list_path": ["items"],
            "fields": {
                "post_id": [{"from": "json", "path": ["entryId"], "transform": [["to_str"]]}],
                "title": [{"from": "json", "path": ["title"], "transform": [["html_unescape"], ["collapse_ws"]]}],
                "category": [{"from": "json", "path": ["magazine", "name"]}],
                "url": [
                    {"from": "template", "value": base + "/m/{category}/t/{post_id}"},
                    {"from": "json", "path": ["url"]},
                ],
                "published_at": [{"from": "json", "path": ["createdAt"]}],
                "author": [{"from": "json", "path": ["user", "username"]}],
                "summary": [{"from": "json", "path": ["body"], "transform": [["collapse_ws"]]}],
                "cover_image": [
                    {"from": "json", "path": ["image", "storageUrl"]},
                    {"from": "json", "path": ["image", "sourceUrl"]},
                ],
            },
        },
        "article": {
            "fetch_kind": "json",
            "url_template": base + "/api/entry/{post_id}",
            "content": [{"from": "json", "path": ["body"]}],
            "re_extract": True,
            "body_empty_acceptable": True,
        },
        "_slug_board": host,
        "_source_url": base + "/",
        "_note": _NOTE,
    }


def _build(m: "re.Match", url: str) -> Optional[dict]:
    return build_config(url)


PATTERNS = [
    (re.compile(r"^https?://[^/?#]+/api/entries(?:\?|$)", re.I), _build),
    (re.compile(r"^https?://[^/?#]+/m/[^/?#]+(?:[/?#].*)?$", re.I), _build),
]
