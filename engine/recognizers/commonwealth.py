"""Common/Commonwealth governance forums -> CommonwealthAdapter."""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlsplit

NAME = "commonwealth"

_NOTE = ("Common/Commonwealth governance forum — SPA shell with public tRPC thread.getThreads API. "
         "CommonwealthAdapter reads the JSON API directly; HTML may contain no static rows.")

_COMMON_HOST_RE = re.compile(
    r"^https?://(?P<host>(?:common\.xyz|commonwealth\.im))/(?P<community>[^/?#]+)/discussions/?(?:[?#].*)?$",
    re.I,
)


def _normalize_base(base_url: str) -> Optional[tuple[str, str]]:
    try:
        parts = urlsplit(base_url)
    except (ValueError, AttributeError):
        return None
    host = (parts.netloc or "").strip().lower()
    if not host or "." not in host:
        return None
    return f"{parts.scheme or 'https'}://{host}", host


def build_config(
    base_url: str,
    community_id: str,
    *,
    order_by: str = "newest",
    source_url: Optional[str] = None,
) -> Optional[dict]:
    norm = _normalize_base(base_url)
    community = (community_id or "").strip().strip("/")
    if norm is None or not community:
        return None
    base, host = norm
    return {
        "version": 1,
        "site": host,
        "board": community,
        "strategy": "handwritten",
        "adapter": "CommonwealthAdapter",
        "kwargs": {
            "base_url": base,
            "community_id": community,
            "order_by": order_by,
        },
        "_slug_board": f"{host}_{community}",
        "_source_url": source_url or f"{base}/{community}/discussions",
        "_note": _NOTE,
    }


def _build_common_host(m: "re.Match", url: str) -> Optional[dict]:
    return build_config(f"https://{m.group('host').lower()}", m.group("community"), source_url=url)


PATTERNS = [
    (_COMMON_HOST_RE, _build_common_host),
]
