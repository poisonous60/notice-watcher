"""Common/Commonwealth governance forum adapter.

Common serves discussion lists through a public tRPC endpoint:
`/api/internal/trpc/thread.getThreads?input=<json>`.
The HTML page is a SPA shell, so the list must be read from that API.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Optional
from urllib.parse import urlsplit

import httpx

from .base import BaseAdapter, NoticePost


def _slugify_title(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug[:96] or "thread"


class CommonwealthAdapter(BaseAdapter):
    polite_sleep_min = 2.0
    polite_sleep_max = 4.0
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        *,
        base_url: str,
        community_id: str,
        order_by: str = "newest",
        limit: int = 20,
        timeout: float = 15.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.community_id = community_id.strip()
        self.order_by = order_by
        self.limit = int(limit)
        parts = urlsplit(self.base_url)
        host = (parts.hostname or "common").lower()
        self.site = host
        self.host = host
        self.board = self.community_id
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
        }

    async def __aenter__(self) -> "CommonwealthAdapter":
        self._client = httpx.AsyncClient(
            headers=self._headers, timeout=self._timeout, follow_redirects=True
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get_json(self, path: str, payload: dict) -> dict:
        async def _do(client: httpx.AsyncClient) -> dict:
            last: Optional[httpx.Response] = None
            for attempt in range(3):
                r = await client.get(
                    f"{self.base_url}{path}",
                    params={"input": json.dumps(payload, separators=(",", ":"))},
                )
                last = r
                if r.status_code == 429:
                    await asyncio.sleep(5 * (attempt + 1))
                    continue
                r.raise_for_status()
                data = r.json()
                return data if isinstance(data, dict) else {}
            assert last is not None
            last.raise_for_status()
            return {}

        if self._client is not None:
            return await _do(self._client)
        async with httpx.AsyncClient(
            headers=self._headers, timeout=self._timeout, follow_redirects=True
        ) as c:
            return await _do(c)

    @staticmethod
    def _unwrap_data(data: dict) -> dict:
        node = ((data.get("result") or {}).get("data") or {})
        if isinstance(node, dict) and isinstance(node.get("json"), dict):
            return node["json"]
        return node if isinstance(node, dict) else {}

    def _thread_url(self, thread_id: str, title: str) -> str:
        return f"{self.base_url}/discussion/{thread_id}-{_slugify_title(title)}"

    async def fetch_list(self, *, page: int = 1, page_size: int = 10) -> list[NoticePost]:
        effective_limit = min(max(int(page_size or self.limit), 1), self.limit)
        payload = {
            "community_id": self.community_id,
            "cursor": page,
            "limit": effective_limit,
            "order_by": self.order_by,
        }
        try:
            data = await self._get_json("/api/internal/trpc/thread.getThreads", payload)
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code in (401, 403, 404):
                return []
            raise
        results = self._unwrap_data(data).get("results") or []
        posts: list[NoticePost] = []
        seen: set[str] = set()
        for row in results:
            if not isinstance(row, dict):
                continue
            thread_id = row.get("id")
            title = row.get("title") or ""
            if thread_id is None or not title:
                continue
            post_id = str(thread_id)
            if post_id in seen:
                continue
            seen.add(post_id)
            body = row.get("body") or ""
            summary = body[:500] if isinstance(body, str) else None
            posts.append(NoticePost(
                site=self.site,
                board=self.board,
                post_id=post_id,
                title=title,
                url=self._thread_url(post_id, title),
                published_at=row.get("created_at"),
                author=None,
                category=row.get("community_id") or self.community_id,
                summary=summary,
                content_html=None,
                raw=row,
            ))
        return posts

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        body = post.raw.get("body") if isinstance(post.raw, dict) else None
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
            content_html=body if isinstance(body, str) else "",
            cover_image=post.cover_image,
            raw=post.raw,
        )
