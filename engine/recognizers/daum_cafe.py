"""다음 카페 모바일 → DaumCafeAdapter (페이지 인라인 JS `articles.push({...})` 파싱).

PC URL(cafe.daum.net/...) / 모바일 URL(m.cafe.daum.net/...) 모두 모바일 어댑터로 정규화 →
config 의 site 는 항상 "m.cafe.daum.net". slug 는 사용자가 준 URL 기준(register.py 가
_source_url 을 그 url 로 덮어씀) — 봇 _is_registered 가 그 slug 로 찾으므로 일관됨.
"""
from __future__ import annotations

import re
from typing import Optional

from ._common import qs

NAME = "daum-cafe"

_RESERVED = {"_c21_", "_rec", "bbs_list", "articles", "search", "info", "join", "memo", "popular"}


def _build(m: "re.Match", url: str) -> Optional[dict]:
    cafe_name = m.group(1)
    board = m.group(2)
    if board in _RESERVED:
        # 레거시 PC URL: cafe.daum.net/<cafe>/_c21_/bbs_list?grpid=...&fldid=Z4os 면 fldid 를 board 로
        if board == "_c21_":
            fldid = qs(url).get("fldid")
            if not fldid:
                return None
            board = fldid
        else:
            return None
    return {
        "version": 1, "site": "m.cafe.daum.net", "board": board,
        "strategy": "handwritten", "adapter": "DaumCafeAdapter",
        "kwargs": {"cafe_name": cafe_name, "board_id": board},
        "_source_url": url,
        "_note": ("다음카페 모바일 — known-platform 자동 인식. 글 목록이 페이지 인라인 JS(var articles=[]; articles.push({...}))로만 와서 "
                  "손어댑터 DaumCafeAdapter 가 그 블록을 regex 파싱 + 본문(div#article) fetch. 비공개·등급제한이면 본문 401/403 → 본문 비워 반환(우회 안 함)."),
    }


PATTERNS = [
    (re.compile(r"//(?:m\.)?cafe\.daum\.net/([^/?#]+)/([^/?#]+)(?:[/?#]|$)", re.I), _build),
]
