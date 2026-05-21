"""PeerTube instance adapter — public JSON API v1."""
from __future__ import annotations

from html import escape
from typing import Optional
from urllib.parse import urljoin, urlsplit

import httpx

from .base import BaseAdapter, NoticePost


class PeerTubeAdapter(BaseAdapter):
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
        sort: str = "-publishedAt",
        timeout: float = 15.0,
    ):
        self.base_url = base_url.rstrip("/")
        host = urlsplit(self.base_url).hostname or "peertube"
        self.site = host
        self.host = host
        self.board = "videos"
        self.sort = (sort or "-publishedAt").strip() or "-publishedAt"
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
        }

    async def __aenter__(self) -> "PeerTubeAdapter":
        self._client = httpx.AsyncClient(
            headers=self._headers, timeout=self._timeout, follow_redirects=True
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get_json(self, path: str, *, params: Optional[dict] = None):
        url = self.base_url + path

        async def _do(client: httpx.AsyncClient):
            r = await client.get(url, params=params)
            if r.status_code in (401, 403, 404):
                return None
            r.raise_for_status()
            return r.json()

        if self._client is not None:
            return await _do(self._client)
        async with httpx.AsyncClient(
            headers=self._headers, timeout=self._timeout, follow_redirects=True
        ) as c:
            return await _do(c)

    async def fetch_list(self, *, page: int = 1, page_size: int = 30) -> list[NoticePost]:
        if page and page > 1:
            return []
        count = max(1, min(int(page_size or 30), 50))
        data = await self._get_json(
            "/api/v1/videos",
            params={"sort": self.sort, "count": count},
        )
        if not isinstance(data, dict):
            return []
        posts: list[NoticePost] = []
        seen: set[str] = set()
        for item in data.get("data") or []:
            if not isinstance(item, dict):
                continue
            pid = item.get("uuid") or item.get("shortUUID") or item.get("id")
            if pid is None:
                continue
            pid_s = str(pid)
            if pid_s in seen:
                continue
            seen.add(pid_s)
            posts.append(self._to_post(item))
        return posts

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        data = await self._get_json(f"/api/v1/videos/{post.post_id}")
        if isinstance(data, dict):
            return self._to_post(data, fallback=post, include_body=True)
        return self._to_post(post.raw or {}, fallback=post, include_body=True)

    def _to_post(
        self,
        item: dict,
        *,
        fallback: Optional[NoticePost] = None,
        include_body: bool = False,
    ) -> NoticePost:
        pid = str(item.get("uuid") or item.get("shortUUID") or (fallback.post_id if fallback else "") or "")
        title = item.get("name") or (fallback.title if fallback else "") or ""
        url = item.get("url") or (f"{self.base_url}/videos/watch/{pid}" if pid else None)
        account = item.get("account") or {}
        channel = item.get("channel") or {}
        category = item.get("category") or {}
        body = self._compose_body(item, local_url=url) if include_body else None
        return NoticePost(
            site=self.site,
            board=self.board,
            post_id=pid,
            title=title,
            url=url,
            published_at=item.get("publishedAt") or (fallback.published_at if fallback else None),
            author=account.get("displayName") or account.get("name") or (fallback.author if fallback else None),
            category=category.get("label") or channel.get("displayName") or (fallback.category if fallback else None),
            summary=item.get("truncatedDescription") or (fallback.summary if fallback else None),
            content_html=body if include_body else (fallback.content_html if fallback else None),
            cover_image=self._absolute(item.get("thumbnailPath") or item.get("previewPath")),
            raw=item,
        )

    def _absolute(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        return urljoin(self.base_url + "/", value)

    @staticmethod
    def _compose_body(item: dict, *, local_url: Optional[str]) -> str:
        parts: list[str] = []
        body = (item.get("description") or item.get("truncatedDescription") or "").strip()
        if body:
            paras = [p.strip() for p in body.split("\n\n") if p.strip()]
            parts.extend(f"<p>{escape(p).replace(chr(10), '<br>')}</p>" for p in paras)
        if local_url:
            parts.append(f'<p><a href="{escape(local_url, quote=True)}">PeerTube에서 보기</a></p>')
        return "\n".join(parts)
