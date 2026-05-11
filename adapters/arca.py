"""아카라이브(arca.live) 어댑터.

probe 결과:
- httpx 정적은 모든 헤더에서 403 (Cloudflare). Playwright stealth만 통과.
- 글 selector: a.vrow.column (광고는 .notice-service, 공지는 .notice 클래스)
- 글 URL: https://arca.live/b/{채널}/{번호}
- 메인 페이지가 SSR로 글 목록을 직접 반환 (별도 JSON API 없음).

사용:
    async with ArcaLiveAdapter(channel="akendfield") as a:
        posts = await a.fetch_list(page=1)
        full = await a.fetch_article(posts[0])

성인 채널은 로그인 필수 — `state_path`에 storage_state 파일 경로를 주면
사전에 헤드풀로 만든 state.json을 재사용한다.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup, Tag

from .base import BaseAdapter, NoticePost


class ArcaLiveAdapter(BaseAdapter):
    site = "arca.live"
    host = "arca.live"
    BASE = "https://arca.live"

    # 광고 = .notice-service, 일반 공지 = .notice (공지 포함 여부 옵션)
    LIST_ROW_SELECTOR = "a.vrow.column"

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        *,
        channel: str,
        include_notices: bool = True,
        category: Optional[str] = None,
        state_path: Optional[Path] = None,
        headless: bool = True,
        nav_timeout_ms: int = 30000,
        idle_timeout_ms: int = 15000,
    ):
        self.channel = channel
        self.board = channel
        self.include_notices = include_notices
        self.category = category  # arca '카테고리 탭' (예: "공식", "정보/공략")
        self.state_path = state_path
        self.headless = headless
        self._nav_timeout = nav_timeout_ms
        self._idle_timeout = idle_timeout_ms

        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._stealth_cls = None

    async def __aenter__(self) -> "ArcaLiveAdapter":
        await self._open_browser()
        return self

    async def __aexit__(self, *exc) -> None:
        await self._close_browser()

    async def _open_browser(self) -> None:
        from playwright.async_api import async_playwright

        try:
            from playwright_stealth import Stealth  # type: ignore
            self._stealth_cls = Stealth
        except ImportError:
            self._stealth_cls = None

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self.headless)
        ctx_kwargs = {
            "viewport": {"width": 1280, "height": 900},
            "locale": "ko-KR",
            "user_agent": self.USER_AGENT,
        }
        if self.state_path and Path(self.state_path).exists():
            ctx_kwargs["storage_state"] = str(self.state_path)
        self._context = await self._browser.new_context(**ctx_kwargs)
        if self._stealth_cls is not None:
            try:
                # playwright-stealth 1.x의 async API
                await self._stealth_cls().apply_stealth_async(self._context)
            except Exception:
                pass
        self._page = await self._context.new_page()

    async def _close_browser(self) -> None:
        try:
            if self._context is not None:
                await self._context.close()
        finally:
            try:
                if self._browser is not None:
                    await self._browser.close()
            finally:
                if self._pw is not None:
                    await self._pw.stop()
        self._pw = self._browser = self._context = self._page = None

    async def _ensure_browser(self):
        if self._page is None:
            await self._open_browser()
        return self._page

    debug_html_dir: Optional[Path] = None  # set by demo

    async def _goto(self, url: str) -> str:
        page = await self._ensure_browser()
        await page.goto(url, wait_until="domcontentloaded", timeout=self._nav_timeout)
        try:
            await page.wait_for_load_state("networkidle", timeout=self._idle_timeout)
        except Exception:
            pass
        html = await page.content()
        if self.debug_html_dir is not None:
            from urllib.parse import quote
            (self.debug_html_dir / f"_debug_{quote(url, safe='')[:80]}.html").write_text(
                html, encoding="utf-8", errors="replace"
            )
        return html

    # ---------- 목록 ----------

    # 절대/상대 URL 모두 매치. ?p=, #anchor 등 무시.
    _ROW_HREF_RE = re.compile(r"(?:^https?://arca\.live)?/b/(?P<board>[^/]+)/(?P<no>\d+)")

    async def fetch_list(self, *, page: int = 1, page_size: int = 30) -> list[NoticePost]:
        params: list[tuple[str, str]] = []
        if self.category:
            params.append(("category", self.category))
        if page > 1:
            params.append(("p", str(page)))
        url = f"{self.BASE}/b/{self.channel}"
        if params:
            url = f"{url}?{urlencode(params, encoding='utf-8')}"
        html = await self._goto(url)
        soup = BeautifulSoup(html, "lxml")

        rows = soup.select(self.LIST_ROW_SELECTOR)
        posts: list[NoticePost] = []
        seen: set[str] = set()
        for row in rows:
            classes = set(row.get("class") or [])
            # notice-service: 다른 채널 광고 / notice-board: 채널 공지
            if "notice-service" in classes:
                continue
            if "notice-board" in classes and not self.include_notices:
                continue

            href = row.get("href") or ""
            m = self._ROW_HREF_RE.match(href)
            if not m or m.group("board") != self.channel:
                continue

            post_id = m.group("no")
            if post_id in seen:
                continue
            seen.add(post_id)

            abs_url = urljoin(self.BASE, href.split("?")[0].split("#")[0])
            posts.append(self._row_to_post(row, post_id, abs_url, classes))
            if len(posts) >= page_size:
                break

        return posts

    def _row_to_post(self, row: Tag, post_id: str, abs_url: str, classes: set[str]) -> NoticePost:
        title_el = row.select_one(".title")
        author_el = row.select_one(".user-info")
        time_el = row.select_one("time")
        category_el = row.select_one(".badge, .category")

        title = self._clean(title_el.get_text(" ", strip=True) if title_el else row.get_text(" ", strip=True))
        author = author_el.get_text(strip=True) if author_el else None
        published = None
        if time_el:
            published = time_el.get("datetime") or time_el.get_text(strip=True)
        category = category_el.get_text(strip=True) if category_el else None

        is_notice = "notice-board" in classes

        return NoticePost(
            site=self.site,
            board=self.channel,
            post_id=post_id,
            title=title,
            url=abs_url,
            published_at=published,
            author=author,
            category=category or ("notice" if is_notice else None),
            summary=None,
            content_html=None,
            cover_image=None,
            raw={
                "row_classes": sorted(classes),
                "is_notice": is_notice,
            },
        )

    @staticmethod
    def _clean(text: str) -> str:
        return " ".join((text or "").split())

    # ---------- 본문 ----------

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        url = post.url or f"{self.BASE}/b/{self.channel}/{post.post_id}"
        html = await self._goto(url)
        soup = BeautifulSoup(html, "lxml")

        title = post.title
        author = post.author
        published = post.published_at
        content_html: Optional[str] = None

        article = soup.select_one("article") or soup.select_one(".article-body, .article-content")
        if article is not None:
            content_el = (
                article.select_one(".article-body, .fr-view, .article-content, .content")
                or article
            )
            content_html = str(content_el)

            t_el = article.select_one(".article-head .title, .title")
            if t_el and not title:
                title = self._clean(t_el.get_text(" ", strip=True))

            a_el = article.select_one(".user-info")
            if a_el:
                author = a_el.get_text(strip=True)
            time_el = article.select_one("time")
            if time_el:
                published = time_el.get("datetime") or time_el.get_text(strip=True)

        return NoticePost(
            site=self.site,
            board=self.channel,
            post_id=post.post_id,
            title=title,
            url=url,
            published_at=published,
            author=author,
            category=post.category,
            summary=post.summary,
            content_html=content_html,
            cover_image=post.cover_image,
            raw={**post.raw, "fetched_url": url},
        )
