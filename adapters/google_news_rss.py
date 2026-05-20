"""Google News RSS 어댑터 — `news.google.com/rss/search?q=<query>` 직접 파싱.

Google 검색 결과 페이지(SERP)는 직접 크롤 불가:
  - `tbm=nws` 등은 게시판 구조가 아니라 검색 결과 → 자동 파이프 article_page_reject 류로 거부.
  - URL 에 휘발 토큰(`sca_esv`/`sxsrf:<ts>`/`ved`) — 만료되어 폴링 baseline 부적합.
  - SERP 직접 스크랩 = CAPTCHA·IP rate-limit·ToS 위반 (docs/크롤링 지침.md 우회 금지).

Google 이 공식 발행하는 News RSS endpoint 가 같은 검색을 *합법·안정* 채널로 노출:
  https://news.google.com/rss/search?q=<query>&hl=<hl>&gl=<gl>&ceid=<ceid>
Feedly·Inoreader 등도 "google search" 구독 시 내부적으로 이 endpoint 를 쓴다.

kwargs:
  query   : 검색어 (Google 검색의 `q` 파라미터).
  hl/gl/ceid : 로케일 (기본 ko / KR / KR:ko).
  timeout : (기본 15)

본문: News RSS <description> 에 헤드라인·출처 스니펫 inline (HTML). 개별 기사 본문은 제3자
사이트에 있고 <link> 는 Google consent/redirect interstitial 이라 따라가지 않음 → 스니펫만.
"""
from __future__ import annotations

import hashlib
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import urlencode

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


class GoogleNewsRssAdapter(BaseAdapter):
    polite_sleep_min = 3.0
    polite_sleep_max = 6.0

    def __init__(
        self,
        *,
        query: str = "",
        feed_url: str = "",
        board: str = "",
        hl: str = "ko",
        gl: str = "KR",
        ceid: str = "KR:ko",
        timeout: float = 15.0,
    ):
        # 두 모드: (1) search — `query` 로 rss/search 피드 합성. (2) feed — `feed_url` 직접
        # (top-stories `news.google.com/rss`, topic `rss/topics/<id>`, section 등 검색 아닌 피드).
        q = str(query or "").strip()
        fu = str(feed_url or "").strip()
        if not q and not fu:
            raise ValueError(f"google news query 또는 feed_url 필요: query={query!r} feed_url={feed_url!r}")
        self.query = q
        self._direct_feed_url = fu
        self.hl = hl or "ko"
        self.gl = gl or "KR"
        self.ceid = ceid or "KR:ko"
        self.site = "news.google.com"
        self.host = "news.google.com"
        self.board = str(board or "").strip() or q or "top"
        self.timeout = float(timeout)
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def _feed_url(self) -> str:
        if self._direct_feed_url:
            return self._direct_feed_url
        qs = urlencode({
            "q": self.query,
            "hl": self.hl,
            "gl": self.gl,
            "ceid": self.ceid,
        })
        return f"https://news.google.com/rss/search?{qs}"

    async def __aenter__(self) -> "GoogleNewsRssAdapter":
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
            return parsedate_to_datetime(rfc822).isoformat()
        except Exception:
            return None

    async def fetch_list(self, *, page: int = 1, page_size: int = 10) -> list[NoticePost]:
        if page > 1:
            return []
        try:
            xml = await self._get_text(self._feed_url)
        except httpx.HTTPStatusError:
            return []
        soup = BeautifulSoup(xml, "xml")
        items = soup.find_all("item")
        posts: list[NoticePost] = []
        for it in items[:page_size]:
            guid_el = it.find("guid")
            link_el = it.find("link")
            guid_text = guid_el.get_text(strip=True) if guid_el else ""
            link = (link_el.get_text(strip=True) if link_el else "")
            # guid = Google News article token (안정 ID지만 300자+ → _STABLE_ID_RE 200자 cap 초과).
            # sha1 해시로 줄임 — 안정·유니크 유지. 원본 토큰은 raw 에 보존.
            ident = guid_text or link
            if not ident:
                continue
            post_id = hashlib.sha1(ident.encode("utf-8")).hexdigest()
            title_el = it.find("title")
            title = title_el.get_text(strip=True) if title_el else ""
            pub_el = it.find("pubDate")
            published_at = self._to_iso(pub_el.get_text(strip=True) if pub_el else None)
            src_el = it.find("source")
            author = src_el.get_text(strip=True) if src_el else None
            desc_el = it.find("description")
            content_html = desc_el.get_text() if desc_el else None
            posts.append(
                NoticePost(
                    site=self.site,
                    board=self.board,
                    post_id=post_id,
                    title=title,
                    url=link or None,
                    published_at=published_at,
                    author=author,
                    category=None,
                    content_html=content_html,
                    raw={"_strategy": "google_news_rss", "_query": self.query, "_guid": ident},
                )
            )
        await self.polite_sleep()
        return posts

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        # News RSS description 에 스니펫 inline. <link> 는 Google consent interstitial 이라 안 따라감.
        return post
