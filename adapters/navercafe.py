"""네이버 카페 어댑터.

probe 결과:
- 정적 SSR 게시판 페이지(`cafe.naver.com/f-e/cafes/{cafeId}/menus/{menuId}?viewType=L`)는
  1페이지 HTML이 SEO용으로 들어 있지만, page 파라미터(`&page=2` 등)는 무시됨 → 페이징은 JSON API 사용.
- 목록 JSON API: `apis.naver.com/cafe-web/cafe-boardlist-api/v1/cafes/{cafeId}/menus/{menuId}/articles?page=&pageSize=&sortBy=TIME&viewType=L`
  menuId=0 은 카페 "전체글" (모든 게시판 합본).
- 카페 sticky 공지 API: `apis.naver.com/cafe-web/cafe-boardlist-api/v1/cafes/{cafeId}/notices/menus/{menuId}`
- 본문 JSON API: `article.cafe.naver.com/gw/v4/cafes/{cafeId}/articles/{articleId}?menuId=&boardType=L&useCafeId=true&requestFrom=A`
- 헤더는 `User-Agent` + `Referer: https://cafe.naver.com/` 면 200.
- robots.txt에 Crawl-Delay 미명시 → 보수치 5초+.

사용:
    async with NaverCafeAdapter(cafe_id=30291108, menu_id=6) as a:
        posts = await a.fetch_list(page=1)
        full = await a.fetch_article(posts[0])

    # cafe_id 모르고 cafe 홈 URL(`cafe.naver.com/<slug>`) 만 있을 때:
    async with NaverCafeAdapter(cafe_slug="gutterlife", menu_id=0) as a:
        posts = await a.fetch_list(page=1)
"""
from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urlencode

import httpx

from .base import BaseAdapter, NoticePost


KST = timezone(timedelta(hours=9))


class NaverCafeAdapter(BaseAdapter):
    site = "cafe.naver.com"
    # apis.naver.com 과 article.cafe.naver.com 두 호스트를 쓰지만,
    # 호스트별 lock 키는 사이트 단위로 묶어 한 어댑터 인스턴스가 동시에 두 호스트를 때려도
    # 같은 사이트 정책 안에서 직렬화되도록 한다.
    host = "naver.com:cafe"

    LIST_API = "https://apis.naver.com/cafe-web/cafe-boardlist-api/v1/cafes/{cafe_id}/menus/{menu_id}/articles"
    NOTICE_API = "https://apis.naver.com/cafe-web/cafe-boardlist-api/v1/cafes/{cafe_id}/notices/menus/{menu_id}"
    ARTICLE_API = "https://article.cafe.naver.com/gw/v4/cafes/{cafe_id}/articles/{article_id}"
    VIEW_URL = (
        "https://cafe.naver.com/f-e/cafes/{cafe_id}/articles/{article_id}"
        "?boardtype=L&menuid={menu_id}&referrerAllArticles=false"
    )

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    HEADERS = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://cafe.naver.com/",
        "Origin": "https://cafe.naver.com",
    }

    CAFE_HOME_URL = "https://cafe.naver.com/{cafe_slug}"
    _CAFE_ID_RE = re.compile(r"g_sClubId\s*=\s*[\"\']?(\d+)")

    def __init__(
        self,
        *,
        cafe_id: Optional[int] = None,
        cafe_slug: Optional[str] = None,
        menu_id: int,
        include_notices: bool = True,
        timeout: float = 15.0,
    ):
        # cafe_id 직접 또는 cafe_slug → 런타임에 해소. 둘 다 없으면 에러.
        if cafe_id is None and not cafe_slug:
            raise ValueError("NaverCafeAdapter: cafe_id 또는 cafe_slug 중 하나 필요")
        self.cafe_id: Optional[int] = int(cafe_id) if cafe_id is not None else None
        self.cafe_slug: Optional[str] = str(cafe_slug) if cafe_slug else None
        self.menu_id = int(menu_id)
        # board 키는 cafe_id 가 정해진 뒤에만 안정적 → 임시는 slug 기반, 해소 후 갱신.
        self.board = (
            f"cafe{self.cafe_id}/menu{self.menu_id}" if self.cafe_id is not None
            else f"cafe-slug-{self.cafe_slug}/menu{self.menu_id}"
        )
        self.include_notices = include_notices
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _resolve_cafe_id(self) -> None:
        """cafe_slug → cafe_id 해소: 카페 홈 HTML 에서 `g_sClubId` 스크랩. 실패 시 ValueError."""
        if self.cafe_id is not None or not self.cafe_slug:
            return
        url = self.CAFE_HOME_URL.format(cafe_slug=self.cafe_slug)
        assert self._client is not None
        r = await self._client.get(url, headers={**self.HEADERS, "Accept": "text/html,*/*"})
        if r.status_code != 200:
            raise ValueError(f"cafe_slug={self.cafe_slug!r} 홈 페이지 응답 {r.status_code}")
        m = self._CAFE_ID_RE.search(r.text)
        if not m:
            raise ValueError(f"cafe_slug={self.cafe_slug!r} 홈에서 g_sClubId 못 찾음 — 비공개 카페 가능성")
        self.cafe_id = int(m.group(1))
        self.board = f"cafe{self.cafe_id}/menu{self.menu_id}"

    async def __aenter__(self) -> "NaverCafeAdapter":
        self._client = httpx.AsyncClient(
            headers=self.HEADERS, timeout=self._timeout, follow_redirects=True
        )
        await self._resolve_cafe_id()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request(self, url: str) -> httpx.Response:
        if self._client is not None:
            return await self._client.get(url)
        async with httpx.AsyncClient(
            headers=self.HEADERS, timeout=self._timeout, follow_redirects=True
        ) as client:
            return await client.get(url)

    # ---------- 공통 ----------

    def _view_url(self, article_id: int | str) -> str:
        return self.VIEW_URL.format(cafe_id=self.cafe_id, article_id=article_id, menu_id=self.menu_id)

    @staticmethod
    def _ts_to_iso(ts_ms: Optional[int]) -> Optional[str]:
        if not ts_ms:
            return None
        try:
            return datetime.fromtimestamp(int(ts_ms) / 1000, tz=KST).isoformat()
        except (TypeError, ValueError, OSError):
            return None

    def _item_to_post(self, item: dict, *, is_notice_row: bool, item_type: str) -> NoticePost:
        article_id = item.get("articleId") or item.get("refArticleId")
        writer = item.get("writerInfo") or {}
        return NoticePost(
            site=self.site,
            board=self.board,
            post_id=str(article_id) if article_id is not None else "",
            title=item.get("subject") or "",
            url=self._view_url(article_id) if article_id is not None else None,
            published_at=self._ts_to_iso(item.get("writeDateTimestamp")),
            author=writer.get("nickName"),
            category=item.get("headName"),
            summary=item.get("summary"),
            content_html=None,
            cover_image=item.get("representImage") or None,
            raw={
                "is_notice_row": is_notice_row,
                "item_type": item_type,
                "head_id": item.get("headId"),
                "menu_id": item.get("menuId"),
                "read_count": item.get("readCount"),
                "comment_count": item.get("commentCount") or item.get("replyArticleCount"),
                "like_count": item.get("likeItCount"),
            },
        )

    # ---------- 목록 ----------

    async def fetch_list(self, *, page: int = 1, page_size: int = 15) -> list[NoticePost]:
        posts: list[NoticePost] = []
        seen_ids: set[str] = set()

        if self.include_notices and page == 1:
            for p in await self._fetch_notices():
                if p.post_id and p.post_id not in seen_ids:
                    seen_ids.add(p.post_id)
                    posts.append(p)
            # 채널의 1페이지 sticky가 비어 있을 수 있어 그래도 일반 글 fetch는 계속

        for p in await self._fetch_articles(page=page, page_size=page_size):
            if p.post_id and p.post_id not in seen_ids:
                seen_ids.add(p.post_id)
                posts.append(p)

        return posts

    async def _fetch_articles(self, *, page: int, page_size: int) -> list[NoticePost]:
        url = self.LIST_API.format(cafe_id=self.cafe_id, menu_id=self.menu_id)
        params = {
            "page": page,
            "pageSize": page_size,
            "sortBy": "TIME",
            "viewType": "L",
        }
        r = await self._request(f"{url}?{urlencode(params)}")
        r.raise_for_status()
        result = (r.json() or {}).get("result") or {}
        article_list = result.get("articleList") or []
        out: list[NoticePost] = []
        for entry in article_list:
            item = entry.get("item") or {}
            t = entry.get("type") or ""
            # 메뉴 페이지의 일반 글: type = "ARTICLE". 광고/추천은 다른 type이므로 스킵.
            if t != "ARTICLE":
                continue
            out.append(self._item_to_post(item, is_notice_row=False, item_type=t))
        return out

    async def _fetch_notices(self) -> list[NoticePost]:
        url = self.NOTICE_API.format(cafe_id=self.cafe_id, menu_id=self.menu_id)
        r = await self._request(url)
        r.raise_for_status()
        result = (r.json() or {}).get("result") or {}
        article_list = result.get("articleList") or []
        out: list[NoticePost] = []
        for entry in article_list:
            item = entry.get("item") or {}
            t = entry.get("type") or ""
            out.append(self._item_to_post(item, is_notice_row=True, item_type=t))
        return out

    # ---------- 본문 ----------

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        if not post.post_id:
            raise ValueError("post.post_id is required")
        url = self.ARTICLE_API.format(cafe_id=self.cafe_id, article_id=post.post_id)
        # 본문 API의 menuId는 *진입한 게시판*을 써야 한다.
        # notice item.menuId는 글의 원본 메뉴라서, 비공개/등급제한 메뉴면 401이 뜸.
        params = {
            "query": "",
            "menuId": self.menu_id,
            "boardType": "L",
            "useCafeId": "true",
            "requestFrom": "A",
        }
        full_url = f"{url}?{urlencode(params)}"
        r = await self._request(full_url)

        # 비회원 차단 글은 401/403. 우회하지 않고 본문 비워서 반환.
        if r.status_code in (401, 403):
            return NoticePost(
                site=self.site,
                board=self.board,
                post_id=post.post_id,
                title=post.title,
                url=post.url or self._view_url(post.post_id),
                published_at=post.published_at,
                author=post.author,
                category=post.category,
                summary=post.summary,
                content_html=None,
                cover_image=post.cover_image,
                raw={
                    **post.raw,
                    "fetched_url": full_url,
                    "fetch_status": r.status_code,
                    "fetch_note": "members-only or restricted",
                },
            )
        r.raise_for_status()

        article = ((r.json() or {}).get("result") or {}).get("article") or {}
        writer = article.get("writer") or {}

        title = article.get("subject") or post.title
        content_html = article.get("contentHtml")
        author = writer.get("nick") or post.author
        category = article.get("head") or post.category
        published = self._ts_to_iso(article.get("writeDate")) or post.published_at

        return NoticePost(
            site=self.site,
            board=self.board,
            post_id=post.post_id,
            title=title,
            url=post.url or self._view_url(post.post_id),
            published_at=published,
            author=author,
            category=category,
            summary=post.summary,
            content_html=content_html,
            cover_image=post.cover_image,
            raw={
                **post.raw,
                "fetched_url": full_url,
                "read_count": article.get("readCount", post.raw.get("read_count")),
                "comment_count": article.get("commentCount", post.raw.get("comment_count")),
                "is_notice_flag": article.get("isNotice"),
                "gdid": article.get("gdid"),
            },
        )
