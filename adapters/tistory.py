"""Tistory 블로그 RSS 어댑터 — `https://<subdomain>.tistory.com/rss` 직접 파싱.

자동 파이프(httpx_html/playwright_html)로 안 풀리는 이유:
  - 데스크톱 카테고리/홈 페이지가 정적 HTML 에 글 행 0~소수만 (skin 따라 빈 shell SPA).
    diagnosis rule 1 `static_vs_headless` 가 일관되게 "정적 응답이 빈 shell" 박음.
  - 스킨이 사이트마다 달라 row_selector 휴리스틱화 불가.
RSS 피드(`<host>/rss`)는 Tistory 가 자동 발행하는 표준 채널 — 최신 30개 글, description 에 본문 inline.

kwargs:
  host    : Tistory subdomain 호스트 (예: `leedakyeong.tistory.com`).
  timeout : (기본 15)

본문: RSS <description> 에 HTML inline 으로 들어있어 별도 fetch 불요. 비공개/RSS 비활성 블로그는
빈 채널 또는 401 → 빈 목록 반환(우회 안 함).
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
_ENTRY_SLUG_RE = re.compile(r"/entry/([^/?#]+)", re.I)
_NUMERIC_RE = re.compile(r"/(\d+)(?:[/?#]|$)")


class TistoryRssAdapter(BaseAdapter):
    polite_sleep_min = 3.0
    polite_sleep_max = 6.0

    def __init__(self, *, host: str, timeout: float = 15.0):
        h = str(host or "").strip().strip("/").lower()
        if not h or ".tistory.com" not in h:
            raise ValueError(f"tistory subdomain host 필요: {host!r}")
        self.tistory_host = h
        self.site = h
        self.host = h
        self.board = h.split(".tistory.com", 1)[0]
        self.timeout = float(timeout)
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "TistoryRssAdapter":
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

    @staticmethod
    def _post_id_from_url(link: str) -> str:
        m = _ENTRY_SLUG_RE.search(link)
        if m:
            return m.group(1)
        m = _NUMERIC_RE.search(link)
        if m:
            return m.group(1)
        return link

    async def fetch_list(self, *, page: int = 1, page_size: int = 10) -> list[NoticePost]:
        if page > 1:
            return []
        url = f"https://{self.tistory_host}/rss"
        try:
            xml = await self._get_text(url)
        except httpx.HTTPStatusError:
            return []
        soup = BeautifulSoup(xml, "xml")
        items = soup.find_all("item")
        posts: list[NoticePost] = []
        for it in items[:page_size]:
            link_el = it.find("link")
            guid_el = it.find("guid")
            link = (link_el.get_text(strip=True) if link_el else "") or (
                guid_el.get_text(strip=True) if guid_el else ""
            )
            if not link:
                continue
            # Tistory RSS <guid> = `https://<host>/<numeric>` (permalink) — *stable* short ID.
            # <link> = `/entry/<slug>` (사용자가 보는 URL). slug 길이 64자 초과 가능 → post_id 로 부적합.
            guid_text = guid_el.get_text(strip=True) if guid_el else ""
            post_id = self._post_id_from_url(guid_text) if guid_text else self._post_id_from_url(link)
            title_el = it.find("title")
            title = title_el.get_text(strip=True) if title_el else ""
            pub_el = it.find("pubDate")
            published_at = self._to_iso(pub_el.get_text(strip=True) if pub_el else None)
            author_el = it.find("author")
            author = (author_el.get_text(strip=True) if author_el else None) or self.board
            cat_el = it.find("category")
            category = cat_el.get_text(strip=True) if cat_el else None
            desc_el = it.find("description")
            content_html = desc_el.get_text() if desc_el else None
            posts.append(
                NoticePost(
                    site=self.site,
                    board=self.board,
                    post_id=post_id,
                    title=title,
                    url=link,
                    published_at=published_at,
                    author=author,
                    category=category,
                    content_html=content_html,
                    raw={"_strategy": "tistory_rss", "_host": self.tistory_host},
                )
            )
        await self.polite_sleep()
        return posts

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        # RSS description 에 본문 inline → 이미 fetch_list 에서 채움. 비어있으면 글페이지 fallback.
        if post.content_html:
            return post
        url = post.url
        if not url:
            return post
        try:
            html = await self._get_text(url)
        except Exception:
            return post
        soup = BeautifulSoup(html, "lxml")
        content_html: Optional[str] = None
        for sel in (
            "div.tt_article_useless_p_margin.contents_style",
            "div.area-view",
            "div.entry-content",
            "div.article_view",
            "div#article",
        ):
            el = soup.select_one(sel)
            if el is not None:
                content_html = str(el)
                break
        d = post.to_dict()
        d["content_html"] = content_html
        d["raw"] = {**(post.raw or {}), "_article_url": url}
        return NoticePost(**d)
