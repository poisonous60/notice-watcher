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
from urllib.parse import urlsplit

from ._common import qs

NAME = "google-news"

_NOTE = ("Google 검색 — known-platform 자동 인식. SERP 직접 크롤 불가(게시판 아님 + 휘발 토큰 + ToS)"
         "라 검색어 `q` 를 Google 공식 News RSS endpoint(news.google.com/rss/search)로 옮겨 수집. "
         "본문은 RSS description 스니펫만(개별 기사는 제3자 + Google consent redirect).")

_NOTE_FEED = ("Google News 공식 RSS 피드 — known-platform 자동 인식 (top-stories `/rss` · "
              "topic `/rss/topics/<id>` · section `/rss/headlines/...`). 검색 아님 → feed_url 직접. "
              "guid 는 300자+ Google 토큰이라 adapter 가 sha1 로 안정 post_id 화 (raw 는 보존). "
              "본문은 RSS description 스니펫만.")

_URL_RE = re.compile(
    r"//(?:www\.)?google\.[a-z.]+/search\b"      # google.com/search (web/news SERP)
    r"|//news\.google\.com/(?:rss/)?search\b",    # news.google.com (rss/)search
    re.I,
)

# 검색 아닌 공식 RSS 피드 — top-stories(`/rss` + query/end), topic(`/rss/topics/<id>`),
# section(`/rss/headlines/...`). `/rss/search`(검색=_URL_RE)·`/rss/articles/<id>`(단일 글) 는 제외
# (둘 다 `/rss` 뒤가 `/topics//headlines//?/$` 아님). 2026-05-20-b batch: top-stories `/rss` 가
# 인식기 미커버 → generic 파이프가 raw guid 로 post_id_stable_shape fail.
_FEED_RE = re.compile(
    r"//news\.google\.com/rss(?:/topics/|/headlines/|/?(?:[?#]|$))",
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


def _build_feed(m: "re.Match", url: str) -> Optional[dict]:
    q = qs(url)
    hl = q.get("hl") or "ko"
    gl = q.get("gl") or "KR"
    ceid = q.get("ceid") or f"{gl}:{hl}"
    path = urlsplit(url).path
    if "/topics/" in path:
        token = path.split("/topics/", 1)[1].split("/")[0]
        board = f"topic_{token[:16]}"
    elif "/headlines/" in path:
        seg = [s for s in path.split("/") if s]
        board = seg[-1].lower() if seg else "headlines"
    else:
        board = f"top_{hl}_{gl}"
    return {
        "version": 1, "site": "news.google.com", "board": board,
        "strategy": "handwritten", "adapter": "GoogleNewsRssAdapter",
        "kwargs": {"feed_url": url, "board": board, "hl": hl, "gl": gl, "ceid": ceid, "timeout": 15.0},
        "_slug_board": f"gnews_{board}",
        "_source_url": url, "_note": _NOTE_FEED,
    }


PATTERNS = [
    (_URL_RE, _build),
    (_FEED_RE, _build_feed),
]
