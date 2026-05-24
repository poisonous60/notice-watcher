from __future__ import annotations

from html import escape
from typing import Any, Optional

from .base import BaseAdapter, NoticePost


class IdxPressReleaseAdapter(BaseAdapter):
    site = "www.idx.co.id"
    host = "www.idx.co.id"
    board = "press-release"
    LIST_URL = "https://www.idx.co.id/en/news/press-release/"

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        *,
        headless: bool = True,
        nav_timeout_ms: int = 60000,
        idle_timeout_ms: int = 10000,
    ):
        self.headless = headless
        self._nav_timeout = nav_timeout_ms
        self._idle_timeout = idle_timeout_ms
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    async def __aenter__(self) -> "IdxPressReleaseAdapter":
        await self._open_browser()
        return self

    async def __aexit__(self, *exc) -> None:
        await self._close_browser()

    async def _open_browser(self) -> None:
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self.headless)
        self._context = await self._browser.new_context(
            viewport={"width": 1366, "height": 900},
            locale="en-US",
            user_agent=self.USER_AGENT,
        )
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

    async def _ensure_page(self):
        if self._page is None:
            await self._open_browser()
        return self._page

    async def _row_data(self) -> list[dict[str, Any]]:
        page = await self._ensure_page()
        await page.goto(self.LIST_URL, wait_until="domcontentloaded", timeout=self._nav_timeout)
        try:
            await page.wait_for_load_state("networkidle", timeout=self._idle_timeout)
        except Exception:
            pass
        rows = await page.evaluate(
            """() => {
                const fetch = (window.__NUXT__ && window.__NUXT__.fetch) || {};
                const key = Object.keys(fetch).find((k) => {
                    const table = fetch[k] && fetch[k].table;
                    return table && Array.isArray(table.rowData);
                });
                return key ? fetch[key].table.rowData : [];
            }"""
        )
        return rows if isinstance(rows, list) else []

    async def fetch_list(self, *, page: int = 1, page_size: int = 10) -> list[NoticePost]:
        rows = await self._row_data()
        start = max(0, page - 1) * page_size
        out: list[NoticePost] = []
        for item in rows[start:start + page_size]:
            post = self._to_post(item)
            if post is not None:
                out.append(post)
        return out

    def _to_post(self, item: dict[str, Any]) -> Optional[NoticePost]:
        post_id = item.get("Id")
        title = self._clean(item.get("Title"))
        if post_id is None or not title:
            return None
        href = None
        for link in item.get("Links") or []:
            if isinstance(link, dict) and link.get("Href"):
                href = str(link["Href"])
                break
        url = f"https://www.idx.co.id{href}" if href and href.startswith("/") else href
        return NoticePost(
            site=self.site,
            board=self.board,
            post_id=str(post_id),
            title=title,
            url=url or self.LIST_URL,
            published_at=item.get("PublishedDate"),
            author=None,
            category="Press Release",
            summary=self._clean(item.get("Summary")),
            content_html=None,
            cover_image=self._abs_media(item.get("ImageUrl")),
            raw={"_strategy": "handwritten", "_item": item},
        )

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        body = post.summary or post.title
        content_html = f"<p>{escape(body)}</p>" if body else None
        return NoticePost(
            site=post.site,
            board=post.board,
            post_id=post.post_id,
            title=post.title,
            url=post.url,
            published_at=post.published_at,
            author=post.author,
            category=post.category,
            summary=post.summary,
            content_html=content_html,
            cover_image=post.cover_image,
            raw={**post.raw, "body_source": "idx_ssr_summary"},
        )

    @staticmethod
    def _clean(value: Any) -> str:
        return " ".join(str(value or "").split())

    @staticmethod
    def _abs_media(value: Any) -> Optional[str]:
        if not value:
            return None
        s = str(value)
        if s.startswith("http://") or s.startswith("https://"):
            return s
        if s.startswith("/"):
            return f"https://www.idx.co.id{s}"
        return s
