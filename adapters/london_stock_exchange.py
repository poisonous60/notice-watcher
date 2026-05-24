"""London Stock Exchange news and insights adapter."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from html import escape
from typing import Optional
from urllib.parse import quote, urljoin, urlsplit

import httpx

from .base import BaseAdapter, NoticePost


_BASE_URL = "https://www.londonstockexchange.com/"
_API_BASE = "https://api.londonstockexchange.com/api/v1"
_BOARD_PATH = "discover/news-and-insights"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.londonstockexchange.com",
    "Referer": "https://www.londonstockexchange.com/",
}


class LondonStockExchangeNewsAdapter(BaseAdapter):
    site = "londonstockexchange.com"
    host = "api.londonstockexchange.com"
    board = _BOARD_PATH
    polite_sleep_min = 5.0
    polite_sleep_max = 8.0

    def __init__(self, *, timeout: float = 20.0):
        self.timeout = float(timeout)
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "LondonStockExchangeNewsAdapter":
        self._client = httpx.AsyncClient(headers=_HEADERS, timeout=self.timeout, follow_redirects=True)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get_json(self, url: str) -> object:
        client = self._client
        if client is None:
            async with httpx.AsyncClient(headers=_HEADERS, timeout=self.timeout, follow_redirects=True) as c:
                r = await c.get(url)
        else:
            r = await client.get(url)
        r.raise_for_status()
        return r.json()

    async def _post_json(self, url: str, body: dict) -> object:
        client = self._client
        if client is None:
            async with httpx.AsyncClient(headers=_HEADERS, timeout=self.timeout, follow_redirects=True) as c:
                r = await c.post(url, json=body)
        else:
            r = await client.post(url, json=body)
        r.raise_for_status()
        return r.json()

    async def _page_payload(self, path: str) -> dict:
        url = f"{_API_BASE}/pages?path={path}&parameters="
        payload = await self._get_json(url)
        if not isinstance(payload, dict):
            raise RuntimeError(f"LSE page payload is not an object: {path}")
        return payload

    @staticmethod
    def _component_value(component: dict) -> dict:
        content = component.get("content")
        if not isinstance(content, list) or not content:
            return {}
        first = content[0] if isinstance(content[0], dict) else {}
        value = first.get("value")
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _latest_tab(page: dict) -> Optional[dict]:
        for component in page.get("components") or []:
            if not isinstance(component, dict) or component.get("type") != "tab-nav":
                continue
            value = LondonStockExchangeNewsAdapter._component_value(component)
            for tab in value.get("contentTabNav") or []:
                if not isinstance(tab, dict):
                    continue
                if str(tab.get("label") or "").strip().lower() == "latest":
                    return tab
        return None

    async def _latest_components(self) -> list[dict]:
        page = await self._page_payload(_BOARD_PATH)
        tab = self._latest_tab(page)
        if not tab:
            raise RuntimeError("LSE latest tab not found")
        modules = [m for m in tab.get("modules") or [] if isinstance(m, dict) and m.get("moduleId")]
        body = {
            "path": _BOARD_PATH,
            "parameters": f"tab%3Dlatest%26tabId%3D{quote(str(tab.get('tabId') or ''), safe='')}",
            "components": [
                {"componentId": quote(str(module["moduleId"]), safe=""), "parameters": None}
                for module in modules
            ],
        }
        payload = await self._post_json(f"{_API_BASE}/components/refresh", body)
        return payload if isinstance(payload, list) else []

    @staticmethod
    def _date_to_iso(value: object) -> Optional[str]:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()

    @staticmethod
    def _post_id(link: str) -> str:
        path = urlsplit(link).path if link.startswith("http") else link
        return path.rstrip("/").split("/")[-1]

    @classmethod
    def _post_from_story(cls, item: dict) -> Optional[NoticePost]:
        title = str(item.get("title") or "").strip()
        link = str(item.get("link") or "").strip()
        post_id = cls._post_id(link)
        if not title or not link or not post_id:
            return None
        tags = item.get("tags")
        category = ", ".join(str(t) for t in tags if t) if isinstance(tags, list) else None
        summary = str(item.get("text") or "").strip() or None
        return NoticePost(
            site=cls.site,
            board=cls.board,
            post_id=post_id,
            title=title,
            url=urljoin(_BASE_URL, link),
            published_at=cls._date_to_iso(item.get("datetime")),
            author="London Stock Exchange",
            category=category,
            summary=summary,
            cover_image=str(item.get("image") or "").strip() or None,
            raw={"_strategy": "london_stock_exchange_news", "_item": item},
        )

    async def fetch_list(self, *, page: int = 1, page_size: int = 10) -> list[NoticePost]:
        if page > 1:
            return []
        posts: list[NoticePost] = []
        seen: set[str] = set()
        for component in await self._latest_components():
            if not isinstance(component, dict):
                continue
            value = self._component_value(component)
            for item in value.get("exploreStoriesResults") or []:
                if not isinstance(item, dict):
                    continue
                post = self._post_from_story(item)
                if post is None or post.post_id in seen:
                    continue
                seen.add(post.post_id)
                posts.append(post)
                if len(posts) >= page_size:
                    return posts
        return posts

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        if not post.url:
            return post
        path = urlsplit(post.url).path.lstrip("/")
        payload = await self._page_payload(path)
        content_html = None
        overrides: dict = {}
        for component in payload.get("components") or []:
            if not isinstance(component, dict) or component.get("type") != "story":
                continue
            value = self._component_value(component)
            content_html = str(value.get("storyText") or "").strip() or None
            if value.get("storyTitle"):
                overrides["title"] = str(value["storyTitle"]).strip()
            published_at = self._date_to_iso(value.get("storyDateTime"))
            if published_at:
                overrides["published_at"] = published_at
            break
        if content_html is None and post.summary:
            content_html = f"<p>{escape(post.summary)}</p>"
        return replace(post, content_html=content_html, raw={**post.raw, "fetched_url": post.url}, **overrides)
