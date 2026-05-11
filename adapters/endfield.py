from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import httpx

from .base import BaseAdapter, NoticePost


class EndfieldAdapter(BaseAdapter):
    """명일방주: 엔드필드 (Gryphline) 공식 공지 어댑터.

    진입: web-news.gryphline.com/api/bulletin (목록) + /api/bulletin/{cid} (본문)
    필수 헤더: Origin / Referer 가 endfield.gryphline.com 이어야 404 안 받음.
    """

    site = "gryphline.endfield"
    host = "web-news.gryphline.com"
    HOST = "https://web-news.gryphline.com"
    APP_CODE = "arknights_endfield_official"
    DEFAULT_LANG = "ko-kr"

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Origin": "https://endfield.gryphline.com",
        "Referer": "https://endfield.gryphline.com/",
    }

    def __init__(
        self,
        *,
        lang: str = DEFAULT_LANG,
        board: str = "all",
        category_filter: Optional[set[str]] = None,
        timeout: float = 15.0,
    ):
        self.lang = lang
        self.board = board
        self.category_filter = category_filter
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "EndfieldAdapter":
        self._client = httpx.AsyncClient(headers=self.HEADERS, timeout=self._timeout)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request_json(self, url: str, *, params: dict) -> dict:
        if self._client is not None:
            r = await self._client.get(url, params=params)
            r.raise_for_status()
            return r.json()
        # context manager 없이 호출된 경우 일회성 client.
        async with httpx.AsyncClient(headers=self.HEADERS, timeout=self._timeout) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            return r.json()

    # API 관찰 결과: pageSize는 서버에서 20으로 강제 cap.
    # 더 크게 요청해도 20만 반환되므로 의미 없음.
    PAGE_SIZE_MAX = 20

    async def fetch_list(self, *, page: int = 1, page_size: int = 10) -> list[NoticePost]:
        ps = min(page_size, self.PAGE_SIZE_MAX)
        params = {
            "lang": self.lang,
            "code": self.APP_CODE,
            "page": page,
            "pageSize": ps,
        }
        payload = await self._request_json(f"{self.HOST}/api/bulletin", params=params)

        if payload.get("code") != 0:
            raise RuntimeError(f"endfield list error: {payload.get('msg')}")

        items = payload.get("data", {}).get("list", []) or []
        posts: list[NoticePost] = []
        for it in items:
            tab = it.get("tab")
            if self.category_filter and tab not in self.category_filter:
                continue
            posts.append(self._to_post(it, content_html=None))
        return posts

    async def fetch_all_pages(
        self,
        *,
        page_size: int = 20,
        max_pages: int = 50,
    ) -> list[NoticePost]:
        """page=1부터 빈 응답까지 순회해 모든 글 목록을 한 번에 수집.

        같은 cid 중복은 자동 제거. 페이지 사이는 어댑터의 polite_sleep.
        """
        all_posts: list[NoticePost] = []
        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            posts = await self.fetch_list(page=page, page_size=page_size)
            new_posts = [p for p in posts if p.post_id not in seen]
            if not posts:
                break
            for p in new_posts:
                seen.add(p.post_id)
            all_posts.extend(new_posts)
            # 빈 페이지 전이라도 마지막 페이지면 그만
            if len(posts) < page_size:
                break
            await self.polite_sleep()
        return all_posts

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        params = {"lang": self.lang, "code": self.APP_CODE}
        payload = await self._request_json(
            f"{self.HOST}/api/bulletin/{post.post_id}", params=params
        )

        if payload.get("code") != 0:
            raise RuntimeError(f"endfield detail error cid={post.post_id}: {payload.get('msg')}")

        return self._to_post(payload.get("data", {}) or {}, content_html=(payload.get("data") or {}).get("data"))

    def _to_post(self, item: dict, *, content_html: Optional[str]) -> NoticePost:
        cid = str(item.get("cid", ""))
        ts = item.get("displayTime")
        published = (
            datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            if isinstance(ts, (int, float))
            else None
        )
        return NoticePost(
            site=self.site,
            board=self.board,
            post_id=cid,
            title=item.get("title") or "",
            url=None,  # 공식 사이트에 글 단독 URL이 없음
            published_at=published,
            author=item.get("author") or None,
            category=item.get("tab"),
            summary=item.get("brief"),
            content_html=content_html,
            cover_image=item.get("cover") or None,
            raw=item,
        )
