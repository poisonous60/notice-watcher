"""Lemmy instances -> LemmyAdapter (public JSON API v3).

Root URLs are intentionally not matched by URL alone: any site has a root URL.
`probe.extract.detect_lemmy_platform` handles root pages after seeing Lemmy
markers in the rendered/static HTML. Direct Lemmy-specific paths are safe to
recognize here.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import quote, urlencode, urlsplit

from ._common import qs

NAME = "lemmy"
_DEFAULT_SORT = "New"
_DEFAULT_TYPE = "Local"

_NOTE = ("Lemmy instance — known-platform 자동 인식. 손어댑터 LemmyAdapter 가 "
         "`/api/v3/post/list?sort=New&limit=...&type_=Local` JSON API 를 호출한다. "
         "HTML UI 가 Anubis/Cloudflare/SSR 문제로 막혀도 공개 API 가 열려 있으면 수집 가능. "
         "post_id 는 `post.post.id`(인스턴스 local id) 를 사용한다; `ap_id` 는 federation origin 이라 "
         "instance polling state 의 고유키로 쓰지 않는다.")


def build_config(
    base_url: str,
    *,
    community_name: Optional[str] = None,
    sort: Optional[str] = None,
    type_: Optional[str] = None,
) -> Optional[dict]:
    parts = urlsplit(base_url)
    host = (parts.netloc or "").strip().lower()
    if not host or "." not in host:
        return None
    base = f"{parts.scheme or 'https'}://{host}"
    community = (community_name or "").strip().strip("/") or None
    sort_value = (sort or "").strip() or _DEFAULT_SORT
    type_value = (type_ or "").strip() or _DEFAULT_TYPE
    kwargs: dict = {"base_url": base}
    board = "local"
    slug_board = host
    source_url = base + "/"
    if community:
        kwargs["community_name"] = community
        board = f"c/{community}"
        slug_board = f"{host}_c_{community}"
        source_url = f"{base}/c/{community}"
    if sort_value != _DEFAULT_SORT:
        kwargs["sort"] = sort_value
    if type_value != _DEFAULT_TYPE:
        kwargs["type_"] = type_value
    if sort_value != _DEFAULT_SORT or type_value != _DEFAULT_TYPE:
        slug_parts = [slug_board]
        if sort_value != _DEFAULT_SORT:
            slug_parts += ["sort", quote(sort_value, safe="")]
        if type_value != _DEFAULT_TYPE:
            slug_parts += ["type", quote(type_value, safe="")]
        slug_board = "_".join(slug_parts)
        source_params = {
            "sort": sort_value,
            "type_": type_value,
        }
        if community:
            source_params["community_name"] = community
        source_url = base + "/api/v3/post/list?" + urlencode(sorted(source_params.items()), encoding="utf-8")
    return {
        "version": 1,
        "site": host,
        "board": board,
        "strategy": "handwritten",
        "adapter": "LemmyAdapter",
        "kwargs": kwargs,
        "_slug_board": slug_board,
        "_source_url": source_url,
        "_note": _NOTE,
    }


def _community_from_path(path: str) -> Optional[str]:
    m = re.match(r"^/c/([^/?#]+)/*$", path or "", re.I)
    if m is None:
        return None
    value = m.group(1).strip()
    if not value or "/" in value:
        return None
    return value


def _build(m: "re.Match", url: str) -> Optional[dict]:
    parts = urlsplit(url)
    community = _community_from_path(parts.path or "")
    query = qs(url)
    return build_config(
        url,
        community_name=community or query.get("community_name"),
        sort=query.get("sort"),
        type_=query.get("type_"),
    )


PATTERNS = [
    (re.compile(r"^https?://[^/?#]+/api/v3/post/list(?:\?|$)", re.I), _build),
]
