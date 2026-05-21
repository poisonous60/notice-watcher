"""Lemmy instance adapter — public JSON API v3.

Lemmy root pages and post lists are often SSR/JS-heavy, and several public
instances put anti-bot HTML in front of the web UI. The API remains the stable
surface for public posts:

  list   <base>/api/v3/post/list?sort=New&limit=N&type_=Local
  detail <base>/api/v3/post?id=<local post id>

`post.post.id` is the instance-local stable ID. `ap_id` can point at a remote
origin post and is not unique for this instance's polling state.
"""
from __future__ import annotations

from html import escape
from typing import Optional
from urllib.parse import urlsplit

import httpx

from .base import BaseAdapter, NoticePost


class LemmyAdapter(BaseAdapter):
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
        community_name: Optional[str] = None,
        sort: str = "New",
        type_: str = "Local",
        timeout: float = 15.0,
    ):
        self.base_url = base_url.rstrip("/")
        host = urlsplit(self.base_url).hostname or "lemmy"
        self.site = host
        self.host = host
        self.community_name = (community_name or "").strip().strip("/") or None
        self.sort = (sort or "New").strip() or "New"
        self.type_ = (type_ or "Local").strip() or "Local"
        self.board = f"c/{self.community_name}" if self.community_name else "local"
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
        }

    async def __aenter__(self) -> "LemmyAdapter":
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
        # Lemmy v3 uses cursor pagination (`page_cursor` / `next_page`) on newer
        # instances. The watcher polls only the first page, so page>1 is skipped.
        if page and page > 1:
            return []
        limit = max(1, min(int(page_size or 30), 50))
        params = {"sort": self.sort, "limit": limit, "type_": self.type_}
        if self.community_name:
            params["community_name"] = self.community_name
        data = await self._get_json("/api/v3/post/list", params=params)
        if not isinstance(data, dict):
            return []
        posts: list[NoticePost] = []
        seen: set[str] = set()
        for view in data.get("posts") or []:
            post = (view or {}).get("post") or {}
            pid = post.get("id")
            if pid is None:
                continue
            pid_s = str(pid)
            if pid_s in seen:
                continue
            seen.add(pid_s)
            posts.append(self._to_post(view))
        return posts

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        data = await self._get_json("/api/v3/post", params={"id": post.post_id})
        if isinstance(data, dict) and isinstance(data.get("post_view"), dict):
            return self._to_post(data["post_view"], fallback=post, include_body=True)
        return self._to_post(post.raw or {}, fallback=post, include_body=True)

    def _to_post(
        self,
        view: dict,
        *,
        fallback: Optional[NoticePost] = None,
        include_body: bool = False,
    ) -> NoticePost:
        post = (view or {}).get("post") or {}
        creator = (view or {}).get("creator") or {}
        community = (view or {}).get("community") or {}
        counts = (view or {}).get("counts") or {}

        pid = str(post.get("id") or (fallback.post_id if fallback else "") or "")
        title = post.get("name") or (fallback.title if fallback else "") or ""
        local_url = f"{self.base_url}/post/{pid}" if pid else (fallback.url if fallback else None)
        body = self._compose_body(post, local_url=local_url) if include_body else None
        published = post.get("published") or counts.get("published") or (fallback.published_at if fallback else None)
        author = creator.get("display_name") or creator.get("name") or (fallback.author if fallback else None)
        category = community.get("title") or community.get("name") or (fallback.category if fallback else None)
        return NoticePost(
            site=self.site,
            board=self.board,
            post_id=pid,
            title=title,
            url=local_url,
            published_at=published,
            author=author,
            category=category,
            summary=(post.get("embed_description") or None),
            content_html=body if include_body else (fallback.content_html if fallback else None),
            cover_image=post.get("thumbnail_url") or (fallback.cover_image if fallback else None),
            raw=view,
        )

    @staticmethod
    def _compose_body(post: dict, *, local_url: Optional[str]) -> str:
        parts: list[str] = []
        body = (post.get("body") or "").strip()
        if body:
            paras = [p.strip() for p in body.split("\n\n") if p.strip()]
            parts.extend(f"<p>{escape(p).replace(chr(10), '<br>')}</p>" for p in paras)
        external_url = (post.get("url") or "").strip()
        if external_url:
            label = post.get("embed_title") or external_url
            parts.append(f'<p><a href="{escape(external_url, quote=True)}">{escape(label)}</a></p>')
        if not parts:
            link = local_url or ""
            parts.append(f'<p>(본문 없음 - <a href="{escape(link, quote=True)}">Lemmy에서 보기</a>)</p>')
        return "\n".join(parts)
