"""인식기들 공용 헬퍼. 밑줄로 시작 — auto-discovery 제외."""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from engine._tracking_query import is_tracking_query

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def qs(url: str) -> dict:
    """URL 쿼리스트링 → dict(첫값만). 값 없는 키는 버림. 추적용 query 자동 drop —
    `?utm_source=fb` 같은 변형 URL 이 unknown query 로 잡혀 fast-path 가 거부되는 걸 막아,
    같은 게시판의 변형들이 한 slug 로 통합되게 한다 (`engine.slug.canonical_url` 와 같은 표 본다)."""
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()
            if v and not is_tracking_query(k)}
