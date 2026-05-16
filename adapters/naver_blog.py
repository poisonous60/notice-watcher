"""네이버 블로그 RSS 어댑터 — `https://rss.blog.naver.com/<blogId>.xml` 직접 파싱.

자동 파이프(httpx_html/playwright_html)로 안 풀리는 이유:
  - 데스크톱 blog.naver.com/<id> 는 iframe 으로 mainFrame 콘텐츠 로드 → 정적 HTML 에 글 행 0개.
  - 모바일 m.blog.naver.com/<id> 는 React SPA → 정적 HTML 에 글 행 0개.
  - PostList.naver 도 SPA 라 row_selector 못 잡음.
RSS 피드(`rss.blog.naver.com/<blogId>.xml`)는 안정적 XML — 최신 30~50개 글. 폴링 충분.

kwargs:
  blog_id            : 네이버 블로그 ID (URL 의 `blog.naver.com/<blog_id>` 또는 `?blogId=<blog_id>`).
  timeout            : (기본 15)

본문 파싱: 어댑터가 `m.blog.naver.com/PostView.naver?blogId=...&logNo=...` 를 받아 `div.se-main-container`
(스마트에디터 ONE) 또는 `div#postViewArea` (구 SE) 를 추출. 실패해도 swallow — content_html=None.

비공개 블로그면 RSS 가 401/빈 채널 → 빈 목록 반환(우회 안 함).
"""
from __future__ import annotations

import re
from email.utils import parsedate_to_datetime
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from .base import BaseAdapter, NoticePost


_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "application/rss+xml, application/xml, text/xml, */*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
}
_LOGNO_RE = re.compile(r"/(\d{6,})(?:[/?#]|$)")


class NaverBlogRssAdapter(BaseAdapter):
    site = "blog.naver.com"
    host = "blog.naver.com"
    polite_sleep_min = 3.0
    polite_sleep_max = 6.0

    def __init__(self, *, blog_id: str, timeout: float = 15.0):
        bid = str(blog_id or "").strip().strip("/")
        if not bid:
            raise ValueError("blog_id 필요")
        self.blog_id = bid
        self.board = bid
        self.timeout = float(timeout)
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "NaverBlogRssAdapter":
        self._client = httpx.AsyncClient(
            headers=_HEADERS, timeout=self.timeout, follow_redirects=True
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get_text(self, url: str) -> str:
        client = self._client
        if client is None:
            async with httpx.AsyncClient(
                headers=_HEADERS, timeout=self.timeout, follow_redirects=True
            ) as c:
                r = await c.get(url)
        else:
            r = await client.get(url)
        r.raise_for_status()
        return r.text

    @staticmethod
    def _to_iso(rfc822: Optional[str]) -> Optional[str]:
        if not rfc822:
            return None
        try:
            dt = parsedate_to_datetime(rfc822)
            return dt.isoformat()
        except Exception:
            return None

    async def fetch_list(self, *, page: int = 1, page_size: int = 10) -> list[NoticePost]:
        # RSS 는 한 페이지(최근 N개) — page>1 은 빈 목록.
        if page > 1:
            return []
        url = f"https://rss.blog.naver.com/{self.blog_id}.xml"
        try:
            xml = await self._get_text(url)
        except httpx.HTTPStatusError:
            return []
        soup = BeautifulSoup(xml, "xml")
        items = soup.find_all("item")
        posts: list[NoticePost] = []
        for it in items[:page_size]:
            guid_el = it.find("guid")
            link_el = it.find("link")
            link = (guid_el.get_text(strip=True) if guid_el else "") or (
                link_el.get_text(strip=True) if link_el else ""
            )
            if not link:
                continue
            m = _LOGNO_RE.search(link)
            post_id = m.group(1) if m else link
            title_el = it.find("title")
            title = title_el.get_text(strip=True) if title_el else ""
            pub_el = it.find("pubDate")
            published_at = self._to_iso(pub_el.get_text(strip=True) if pub_el else None)
            author_el = it.find("author")
            author = (author_el.get_text(strip=True) if author_el else None) or self.blog_id
            cat_el = it.find("category")
            category = cat_el.get_text(strip=True) if cat_el else None
            posts.append(
                NoticePost(
                    site=self.site,
                    board=self.board,
                    post_id=str(post_id),
                    title=title,
                    url=link,
                    published_at=published_at,
                    author=author,
                    category=category,
                    raw={"_strategy": "naver_blog_rss", "_blog_id": self.blog_id},
                )
            )
        await self.polite_sleep()
        return posts

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        log_no = post.post_id
        url = f"https://m.blog.naver.com/PostView.naver?blogId={self.blog_id}&logNo={log_no}"
        try:
            html = await self._get_text(url)
        except Exception:
            return post
        soup = BeautifulSoup(html, "lxml")
        content_html: Optional[str] = None
        for sel in ("div.se-main-container", "div#postViewArea", "div#post-view"):
            el = soup.select_one(sel)
            if el is not None:
                content_html = str(el)
                break
        d = post.to_dict()
        d["content_html"] = content_html
        d["raw"] = {**(post.raw or {}), "_article_url": url}
        return NoticePost(**d)
