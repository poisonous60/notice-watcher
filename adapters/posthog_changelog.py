"""PostHog changelog adapter using Gatsby page-data JSON.

The changelog page exposes all entries in Gatsby page-data, but the array is
oldest-first. Polling needs newest-first rows, so this adapter reverses the
nodes before returning posts.
"""
from __future__ import annotations

from html import escape
from typing import Optional

import httpx

from .base import BaseAdapter, NoticePost


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://posthog.com/changelog",
}


class PostHogChangelogAdapter(BaseAdapter):
    site = "posthog.com"
    host = "posthog.com"
    board = "changelog"
    polite_sleep_min = 5.0
    polite_sleep_max = 8.0

    def __init__(
        self,
        *,
        url: str = "https://posthog.com/page-data/changelog/page-data.json",
        timeout: float = 15.0,
    ):
        self.url = url
        self.timeout = float(timeout)
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "PostHogChangelogAdapter":
        self._client = httpx.AsyncClient(headers=_HEADERS, timeout=self.timeout, follow_redirects=True)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get_json(self) -> dict:
        client = self._client
        if client is None:
            async with httpx.AsyncClient(headers=_HEADERS, timeout=self.timeout, follow_redirects=True) as c:
                r = await c.get(self.url)
        else:
            r = await client.get(self.url)
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _date_to_iso(value: object) -> Optional[str]:
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None
        if "T" in text:
            return text
        return f"{text}T00:00:00+00:00"

    @staticmethod
    def _content_html(node: dict) -> Optional[str]:
        desc = str(node.get("description") or "").strip()
        if not desc:
            return None
        return "<p>" + escape(desc).replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"

    @staticmethod
    def _url_for(node: dict) -> str:
        cta = node.get("cta") if isinstance(node.get("cta"), dict) else {}
        cta_url = str(cta.get("url") or "").strip()
        if cta_url:
            return cta_url
        github_urls = node.get("githubUrls")
        if isinstance(github_urls, list) and github_urls:
            first = str(github_urls[0] or "").strip()
            if first:
                return first
        return f"https://posthog.com/changelog#{node.get('id')}"

    async def fetch_list(self, *, page: int = 1, page_size: int = 10) -> list[NoticePost]:
        if page > 1:
            return []
        payload = await self._get_json()
        nodes = (((payload.get("result") or {}).get("data") or {}).get("allRoadmap") or {}).get("nodes") or []
        posts: list[NoticePost] = []
        for node in reversed(nodes):
            if not isinstance(node, dict):
                continue
            post_id = str(node.get("id") or "").strip()
            title = str(node.get("title") or "").strip()
            if not post_id or not title:
                continue
            posts.append(
                NoticePost(
                    site=self.site,
                    board=self.board,
                    post_id=post_id,
                    title=title,
                    url=self._url_for(node),
                    published_at=self._date_to_iso(node.get("date")),
                    author="PostHog",
                    category=(((node.get("topic") or {}).get("data") or {}).get("attributes") or {}).get("label"),
                    summary=str(node.get("description") or "").strip() or None,
                    content_html=self._content_html(node),
                    raw={"_strategy": "posthog_changelog", "_item": node},
                )
            )
            if len(posts) >= page_size:
                break
        return posts

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        return post
