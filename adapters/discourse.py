"""Discourse 포럼 어댑터 — 공개 JSON API (`/latest.json`, `/t/<id>.json`).

Discourse 는 거의 모든 페이지 URL 뒤에 `.json` 을 붙이면 같은 데이터를 JSON 으로 준다.
  목록: `<base>/latest.json` — `{"topic_list": {"topics": [{"id","slug","title","created_at",...}]}}`
  카테고리: `<base>/c/<cat_slug>/<cat_id>.json` — 같은 shape
  본문: `<base>/t/<topic_id>.json` — `{"post_stream": {"posts": [{"id","cooked",...}]}}`
        `post_stream.posts[0]` = OP. `cooked` 가 렌더된 본문 HTML.
        topic URL: `<base>/t/<slug>/<id>`

쓰는 사이트: discuss.python.org, meta.discourse.org, forum.djangoproject.com, users.rust-lang.org,
discuss.huggingface.co, forum.godotengine.org, forum.bubble.io, forum.knime.com 등 다수.
사이트마다 카테고리/태그/배지가 달라도 위 두 엔드포인트 shape 은 동일하므로 한 어댑터로 충분.

자동 파이프 실패 패턴: `/latest` 정적 HTML 은 Ember.js shell 이라 `tbody.topic-list-body > tr.topic-list-item`
가 정적에 없음 → `posts_nonempty: 0건`. 자동 retry 가 `httpx_json` `list_path=['topic_list','topics']`
까지 도달해도 본문 fetch URL template 추측이 어려워 `article_body_len` 실패. JSON API 직접 호출이 안정.

정책:
  - User-Agent 필수(기본 Chrome UA), `Accept: application/json`. 헤더 외 우회 없음.
  - 비공개/login-required 토픽은 `cooked` 가 비어 옴 — `content_html=""` 으로 반환 (우회 X).

kwargs:
  base_url           : "https://discuss.python.org" (trailing slash 제거)
  category_slug      : 주어지면 `/c/<slug>/<id>.json` 사용 (`category_id` 도 필요)
  category_id        : int
  timeout            : httpx timeout(기본 15.0)
"""
from __future__ import annotations

import asyncio
from typing import Optional
from urllib.parse import urlsplit

import httpx

from .base import BaseAdapter, NoticePost


class DiscourseAdapter(BaseAdapter):
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
        category_slug: Optional[str] = None,
        category_id: Optional[int] = None,
        timeout: float = 15.0,
    ):
        self.base_url = base_url.rstrip("/")
        host = urlsplit(self.base_url).hostname or "discourse"
        self.site = host
        self.host = host
        self.category_slug = (category_slug or "").strip() or None
        self.category_id = int(category_id) if category_id is not None else None
        self.board = (
            f"c/{self.category_slug}/{self.category_id}"
            if self.category_slug and self.category_id is not None
            else "latest"
        )
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
        }

    async def __aenter__(self) -> "DiscourseAdapter":
        self._client = httpx.AsyncClient(
            headers=self._headers, timeout=self._timeout, follow_redirects=True
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get_json(self, url: str, *, params: Optional[dict] = None):
        async def _do(client: httpx.AsyncClient):
            last: Optional[httpx.Response] = None
            for attempt in range(3):
                r = await client.get(url, params=params)
                last = r
                if r.status_code == 429:
                    await asyncio.sleep(5 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r.json()
            assert last is not None
            last.raise_for_status()
            return last.json()

        if self._client is not None:
            return await _do(self._client)
        async with httpx.AsyncClient(
            headers=self._headers, timeout=self._timeout, follow_redirects=True
        ) as c:
            return await _do(c)

    def _list_url(self) -> str:
        if self.category_slug and self.category_id is not None:
            return f"{self.base_url}/c/{self.category_slug}/{self.category_id}.json"
        return f"{self.base_url}/latest.json"

    def _topic_url(self, topic_id, slug: Optional[str]) -> str:
        if slug:
            return f"{self.base_url}/t/{slug}/{topic_id}"
        return f"{self.base_url}/t/{topic_id}"

    async def fetch_list(self, *, page: int = 1, page_size: int = 30) -> list[NoticePost]:
        if page and page > 1:
            return []
        try:
            data = await self._get_json(self._list_url())
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code in (401, 403, 404):
                return []
            raise
        if not isinstance(data, dict) or "topic_list" not in data:
            return []
        topics = ((data.get("topic_list") or {}).get("topics") or [])
        posts: list[NoticePost] = []
        seen: set[str] = set()
        for t in topics:
            tid = t.get("id")
            if tid is None:
                continue
            tid_s = str(tid)
            if tid_s in seen:
                continue
            seen.add(tid_s)
            slug = t.get("slug") or ""
            posts.append(NoticePost(
                site=self.site,
                board=self.board,
                post_id=tid_s,
                title=(t.get("title") or t.get("fancy_title") or ""),
                url=self._topic_url(tid_s, slug),
                published_at=t.get("created_at") or t.get("last_posted_at"),
                author=None,
                category=None,
                summary=None,
                content_html=None,
                raw=t,
            ))
        return posts

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        tid = post.post_id
        cooked: str = ""
        author = post.author
        data = None
        try:
            data = await self._get_json(f"{self.base_url}/t/{tid}.json")
        except httpx.HTTPStatusError as e:
            if e.response is None or e.response.status_code not in (401, 403, 404):
                raise
        if isinstance(data, dict):
            posts = (data.get("post_stream") or {}).get("posts") or []
            if posts:
                op = posts[0] or {}
                cooked = op.get("cooked") or ""
                author = op.get("username") or op.get("name") or author
        return NoticePost(
            site=post.site,
            board=post.board,
            post_id=post.post_id,
            title=post.title,
            url=post.url,
            published_at=post.published_at,
            author=author,
            category=post.category,
            summary=None,
            content_html=cooked,
            cover_image=None,
            raw=post.raw,
        )
