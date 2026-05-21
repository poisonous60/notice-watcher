"""Airtable newsroom adapter.

The /whatsnew page currently exposes no update rows. Airtable's public update
cards live in /newsroom as Next.js page data; the rendered HTML duplicates and
reorders cards, so parse the page data directly and sort newest-first.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from .base import BaseAdapter, NoticePost


_BASE_URL = "https://www.airtable.com/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


class AirtableNewsroomAdapter(BaseAdapter):
    site = "Airtable"
    host = "www.airtable.com"
    board = "whatsnew"
    polite_sleep_min = 5.0
    polite_sleep_max = 8.0

    def __init__(
        self,
        *,
        url: str = "https://www.airtable.com/newsroom",
        source_url: str = "https://www.airtable.com/whatsnew",
        timeout: float = 20.0,
    ):
        self.url = url
        self.source_url = source_url
        self.timeout = float(timeout)
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "AirtableNewsroomAdapter":
        self._client = httpx.AsyncClient(headers=_HEADERS, timeout=self.timeout, follow_redirects=True)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get_text(self, url: str) -> str:
        client = self._client
        if client is None:
            async with httpx.AsyncClient(headers=_HEADERS, timeout=self.timeout, follow_redirects=True) as c:
                r = await c.get(url)
        else:
            r = await client.get(url)
        r.raise_for_status()
        return r.text

    @staticmethod
    def _next_data(html: str) -> dict:
        soup = BeautifulSoup(html, "lxml")
        script = soup.select_one("script#__NEXT_DATA__")
        if script is None:
            raise RuntimeError("Airtable newsroom: __NEXT_DATA__ script not found")
        raw = script.get_text() or ""
        if not raw.strip():
            raise RuntimeError("Airtable newsroom: __NEXT_DATA__ script empty")
        return json.loads(raw)

    @staticmethod
    def _parse_date(value: object) -> Optional[str]:
        text = str(value or "").strip()
        if not text:
            return None
        for fmt in ("%b %d, %Y", "%B %d, %Y"):
            try:
                return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).isoformat()
            except ValueError:
                continue
        return None

    @staticmethod
    def _image_url(item: dict) -> Optional[str]:
        hero = item.get("heroImage") if isinstance(item.get("heroImage"), dict) else {}
        fields = hero.get("fields") if isinstance(hero.get("fields"), dict) else {}
        file_obj = fields.get("file") if isinstance(fields.get("file"), dict) else {}
        url = str(file_obj.get("url") or "").strip()
        if not url:
            return None
        if url.startswith("//"):
            return f"https:{url}"
        return urljoin(_BASE_URL, url)

    @classmethod
    def _post_from_card(cls, item: dict) -> Optional[NoticePost]:
        link = str(item.get("cardLink") or "").strip()
        title = str(item.get("cardTitle") or "").strip()
        if not link or not title:
            return None
        post_id = link.rstrip("/").split("/")[-1]
        published_at = cls._parse_date(item.get("cardTopic"))
        return NoticePost(
            site=cls.site,
            board=cls.board,
            post_id=post_id,
            title=title,
            url=urljoin(_BASE_URL, link),
            published_at=published_at,
            author="Airtable",
            category=str(item.get("articlesCount") or "").strip() or None,
            cover_image=cls._image_url(item),
            raw={"_strategy": "airtable_newsroom", "_item": item},
        )

    async def fetch_list(self, *, page: int = 1, page_size: int = 10) -> list[NoticePost]:
        if page > 1:
            return []
        data = self._next_data(await self._get_text(self.url))
        page_props = (data.get("props") or {}).get("pageProps") or {}
        cards = page_props.get("tiledViewData") or page_props.get("featuredNewsData") or []
        posts = [p for item in cards if isinstance(item, dict) for p in [self._post_from_card(item)] if p is not None]
        posts.sort(key=lambda p: p.published_at or "", reverse=True)
        return posts[:page_size]

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        if not post.url:
            return post
        html = await self._get_text(post.url)
        soup = BeautifulSoup(html, "lxml")
        content = soup.select_one("section[class*='richTextSection']") or soup.select_one("main")
        content_html = str(content) if content is not None else None
        return replace(post, content_html=content_html, raw={**post.raw, "fetched_url": post.url})
