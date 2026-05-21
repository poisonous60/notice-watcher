"""디시인사이드 미니갤러리 → DCInsideMGalleryAdapter."""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import quote, urlencode

from ._common import qs

NAME = "dcinside-mgallery"

# 어댑터가 직접 다루는 키 — list_params 로 넘기지 않음.
#   id   = 갤러리 식별자 (gallery_id kwarg)
#   page = 페이지네이션 (fetch_list 가 page 인자로 부착)
_RESERVED = {"id", "page"}


def _build(m: "re.Match", url: str) -> Optional[dict]:
    q = qs(url)  # tracking·빈값 query 는 이미 제거됨
    gallery_id = q.get("id")
    if not gallery_id:
        return None
    # 나머지 list-필터 쿼리(exception_mode/s_type/s_keyword/sort_type/search_head …) 는
    # 전부 보존 → 개념글·검색·정렬·말머리 탭이 각각 별 feed 로 등록된다.
    filters = {k: v for k, v in q.items() if k not in _RESERVED}

    kwargs: dict = {"gallery_id": gallery_id, "include_notices": True}
    src_params = [("id", gallery_id)]
    slug_parts = [gallery_id]
    if filters:
        kwargs["list_params"] = filters
        for k in sorted(filters):
            src_params.append((k, filters[k]))
            # arca-live 처럼 한글 키워드는 url-encode 해서 slug 에 보존.
            slug_parts += [k, quote(filters[k], safe="")]
    src = "https://gall.dcinside.com/mgallery/board/lists/?" + urlencode(src_params, encoding="utf-8")

    return {
        "version": 1, "site": "dcinside.mgallery", "board": gallery_id,
        "strategy": "handwritten", "adapter": "DCInsideMGalleryAdapter",
        "kwargs": kwargs,
        "_slug_board": "_".join(slug_parts),
        "_source_url": src,
        "_note": "디시인사이드 미니갤 — known-platform 자동 인식. 손어댑터 DCInsideMGalleryAdapter. robots Crawl-Delay 30 준수(폴링 느림).",
    }


PATTERNS = [
    (re.compile(r"//gall\.dcinside\.com/mgallery/board/(?:lists|view)/?\?", re.I), _build),
]
