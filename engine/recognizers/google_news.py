"""Google 검색 → GoogleNewsRssAdapter (Google News RSS endpoint 직접 파싱).

Google 검색 결과 페이지(SERP)는 게시판 구조가 아니라 자동 파이프가 거부(article_page_reject 류)
+ URL 휘발 토큰(`sca_esv`/`sxsrf`/`ved`)으로 폴링 baseline 부적합 + SERP 직접 스크랩은 ToS 위반.
대신 Google 공식 News RSS endpoint(`news.google.com/rss/search?q=`)로 검색어를 옮겨 합법·안정 수집.

사용자가 어떤 Google 검색 URL 을 줘도 `q` 추출 → 그 검색어의 News RSS 피드로 등록:
  - https://www.google.com/search?q=<query>&tbm=nws&...    (뉴스 탭 SERP)
  - https://www.google.com/search?q=<query>&...            (일반 검색 — 뉴스 RSS 로 매핑)
  - https://news.google.com/search?q=<query>
  - https://news.google.com/rss/search?q=<query>&hl=ko&gl=KR&ceid=KR:ko  (이미 RSS)

로케일: URL 에 hl/gl/ceid 있으면 그대로, 없으면 ko/KR/KR:ko 기본. ceid 없고 hl·gl 있으면 `<gl>:<hl>` 합성.
`q` 없는 URL(검색 아님)은 None → 일반 파이프라인 폴백.
"""
from __future__ import annotations

import re
from typing import Optional

from ._common import qs

NAME = "google-news"

_NOTE = ("Google 검색 — known-platform 자동 인식. SERP 직접 크롤 불가(게시판 아님 + 휘발 토큰 + ToS)"
         "라 검색어 `q` 를 Google 공식 News RSS endpoint(news.google.com/rss/search)로 옮겨 수집. "
         "본문은 RSS description 스니펫만(개별 기사는 제3자 + Google consent redirect).")

_URL_RE = re.compile(
    r"//(?:www\.)?google\.[a-z.]+/search\b"      # google.com/search (web/news SERP)
    r"|//news\.google\.com/(?:rss/)?search\b",    # news.google.com (rss/)search
    re.I,
)


def _build(m: "re.Match", url: str) -> Optional[dict]:
    q = qs(url)
    query = q.get("q")
    if not query:
        return None
    hl = q.get("hl") or "ko"
    gl = q.get("gl") or "KR"
    ceid = q.get("ceid") or f"{gl}:{hl}"
    return {
        "version": 1, "site": "news.google.com", "board": query,
        "strategy": "handwritten", "adapter": "GoogleNewsRssAdapter",
        "kwargs": {"query": query, "hl": hl, "gl": gl, "ceid": ceid, "timeout": 15.0},
        "_slug_board": f"gnews_{query}",
        "_source_url": url, "_note": _NOTE,
    }


PATTERNS = [
    (_URL_RE, _build),
]
