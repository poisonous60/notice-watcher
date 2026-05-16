"""네이버 블로그 → NaverBlogRssAdapter (RSS 피드 직접 파싱).

사용자가 *블로그 인덱스* 또는 *개별 글* 어느 URL 을 줘도 blog_id 추출 → blog 단위 등록.
개별 글 URL 폼:
  - https://blog.naver.com/<blogId>/<logNo>
  - https://blog.naver.com/PostView.naver?blogId=<blogId>&logNo=<logNo>
  - https://m.blog.naver.com/<blogId>/<logNo>
  - https://m.blog.naver.com/PostView.naver?blogId=<blogId>&logNo=<logNo>
  - https://m.blog.naver.com/PostView.nhn?blogId=<blogId>&logNo=<logNo>   (legacy)
블로그 인덱스 URL 폼:
  - https://blog.naver.com/<blogId>
  - https://m.blog.naver.com/<blogId>
  - https://blog.naver.com/PostList.naver?blogId=<blogId>
"""
from __future__ import annotations

import re
from typing import Optional

from ._common import qs

NAME = "naver-blog"

_NOTE = ("네이버 블로그 — known-platform 자동 인식. 손어댑터 NaverBlogRssAdapter 가 "
         "rss.blog.naver.com/<blogId>.xml 을 직접 파싱(자동 httpx_html/playwright_html 은 "
         "데스크톱 iframe·모바일 SPA 라 글 행 0개로 실패). 사용자가 개별 글 URL 을 줘도 blog_id "
         "추출해 blog 단위로 등록. 본문은 m.blog.naver.com/PostView.naver 에서 se-main-container/postViewArea 추출.")

_RESERVED = {
    "PostView.naver", "PostView.nhn", "PostList.naver", "PostList.nhn",
    "Recommendation.naver", "Search.naver", "rss", "BlogHome.naver",
    "MyBlogHome.naver", "CheckIn.naver", "PostSearchList.naver",
    "PostThumbnailAlbumList.naver", "FollowList.naver",
}


def _cfg(blog_id: str, url: str) -> dict:
    return {
        "version": 1, "site": "blog.naver.com", "board": blog_id,
        "strategy": "handwritten", "adapter": "NaverBlogRssAdapter",
        "kwargs": {"blog_id": blog_id, "timeout": 15.0},
        "_slug_board": blog_id,
        "_source_url": url, "_note": _NOTE,
    }


def _from_path(m: "re.Match", url: str) -> Optional[dict]:
    blog_id = m.group(1)
    if not blog_id or blog_id in _RESERVED:
        return None
    return _cfg(blog_id, url)


def _from_query(m: "re.Match", url: str) -> Optional[dict]:
    q = qs(url)
    blog_id = q.get("blogId") or q.get("blogid")
    if not blog_id or blog_id in _RESERVED:
        return None
    return _cfg(blog_id, url)


PATTERNS = [
    # PostView.naver/.nhn / PostList.naver — blogId 쿼리. 가장 명확하므로 먼저.
    (re.compile(r"//(?:m\.)?blog\.naver\.com/(?:PostView|PostList)\.(?:naver|nhn)\b", re.I), _from_query),
    # /<blogId>/<logNo> — 개별 글
    (re.compile(r"//(?:m\.)?blog\.naver\.com/([A-Za-z0-9_-]+)/\d{6,}\b", re.I), _from_path),
    # /<blogId> — 블로그 홈
    (re.compile(r"//(?:m\.)?blog\.naver\.com/([A-Za-z0-9_-]+)/?(?:\?|#|$)", re.I), _from_path),
]
