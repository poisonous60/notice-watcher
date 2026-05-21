"""PeerTube instances -> PeerTubeAdapter (public JSON API v1)."""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import quote, urlsplit

from ._common import qs

NAME = "peertube"

_NOTE = ("PeerTube instance — known-platform 자동 인식. 손어댑터 PeerTubeAdapter 가 "
         "`/api/v1/videos?sort=-publishedAt&count=...` JSON API 를 호출한다. "
         "post_id 는 `uuid`, title 은 `name`, published_at 은 `publishedAt` 를 사용한다.")


_DEFAULT_SORT = "-publishedAt"


def build_config(base_url: str, *, sort: Optional[str] = None) -> Optional[dict]:
    parts = urlsplit(base_url)
    host = (parts.netloc or "").strip().lower()
    if not host or "." not in host:
        return None
    base = f"{parts.scheme or 'https'}://{host}"
    sort_value = (sort or "").strip() or _DEFAULT_SORT
    kwargs: dict = {"base_url": base}
    slug_board = host
    source_url = base + "/"
    if sort_value != _DEFAULT_SORT:
        kwargs["sort"] = sort_value
        slug_board = f"{host}_sort_{quote(sort_value, safe='')}"
        source_url = f"{base}/api/v1/videos?sort={quote(sort_value, safe='')}"
    return {
        "version": 1,
        "site": host,
        "board": "videos",
        "strategy": "handwritten",
        "adapter": "PeerTubeAdapter",
        "kwargs": kwargs,
        "_slug_board": slug_board,
        "_source_url": source_url,
        "_note": _NOTE,
    }


def _build(m: "re.Match", url: str) -> Optional[dict]:
    return build_config(url, sort=qs(url).get("sort"))


PATTERNS = [
    (re.compile(r"^https?://[^/?#]+/api/v1/videos(?:\?|$)", re.I), _build),
]
