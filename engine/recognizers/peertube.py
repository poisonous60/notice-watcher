"""PeerTube instances -> PeerTubeAdapter (public JSON API v1)."""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlsplit

NAME = "peertube"

_NOTE = ("PeerTube instance — known-platform 자동 인식. 손어댑터 PeerTubeAdapter 가 "
         "`/api/v1/videos?sort=-publishedAt&count=...` JSON API 를 호출한다. "
         "post_id 는 `uuid`, title 은 `name`, published_at 은 `publishedAt` 를 사용한다.")


def build_config(base_url: str) -> Optional[dict]:
    parts = urlsplit(base_url)
    host = (parts.netloc or "").strip().lower()
    if not host or "." not in host:
        return None
    base = f"{parts.scheme or 'https'}://{host}"
    return {
        "version": 1,
        "site": host,
        "board": "videos",
        "strategy": "handwritten",
        "adapter": "PeerTubeAdapter",
        "kwargs": {"base_url": base},
        "_slug_board": host,
        "_source_url": base + "/",
        "_note": _NOTE,
    }


def _build(m: "re.Match", url: str) -> Optional[dict]:
    return build_config(url)


PATTERNS = [
    (re.compile(r"^https?://[^/?#]+/api/v1/videos(?:\?|$)", re.I), _build),
]
