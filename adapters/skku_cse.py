"""성균관대학교 소프트웨어학과 공지사항 어댑터.

probe 결과:
- httpx S1.H1 (UA만)으로 200 OK. Cloudflare 없음, JS 불필요.
- robots.txt: crawl-delay 없음, disallow 없음 → 5초+ 보수치 권장.
- 목록 selector: ul.board-list-wrap > li (페이지당 10건)
- 글 URL 패턴: ?mode=view&articleNo={N}&srCategoryId1={cid}&article.offset=0&articleLimit=10
- 본문 selector: div.fr-view (제목: div.board-view-title-wrap > h4)
- 카테고리: span.c-board-list-category 안의 [학사]/[행사]/[졸업평가] 등
- 작성일 형식: YYYY-MM-DD (KST 가정)

카테고리(srCategoryId1):
- 1582 = 소프트웨어학과 학부 공지
- 다른 카테고리도 있을 수 있으나 현재 학부 공지 1582만 검증.

사용:
    async with SkkuCseAdapter(category_id=1582) as a:
        posts = await a.fetch_list(page=1)
        full = await a.fetch_article(posts[0])
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin, urlencode

import httpx
from bs4 import BeautifulSoup, Tag

from .base import BaseAdapter, NoticePost


class SkkuCseAdapter(BaseAdapter):
    site = "cse.skku.edu"
    host = "cse.skku.edu"
    BASE = "https://cse.skku.edu"
    LIST_PATH = "/cse/notice.do"

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    HEADERS = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    }

    _DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    def __init__(
        self,
        *,
        category_id: int = 1582,
        timeout: float = 15.0,
        proxy_url: Optional[str] = None,
    ):
        """
        category_id: srCategoryId1 값. 기본 1582 (소프트웨어학과 학부 공지)
        proxy_url: 직접 호출이 막힐 때 사용할 프록시 베이스. None이면 직접 호출.
                   ScraperAPI 같은 형태: "https://api.scraperapi.com?api_key=...&url={target}"
                   {target} 자리에 URL-encoded 원본 URL을 끼움. None이면 미사용.
        """
        self.category_id = category_id
        self.board = str(category_id)
        self._timeout = timeout
        self._proxy_url = proxy_url
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "SkkuCseAdapter":
        self._client = httpx.AsyncClient(
            headers=self.HEADERS, timeout=self._timeout, follow_redirects=True
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _fetch(self, url: str) -> str:
        if self._proxy_url:
            from urllib.parse import quote
            fetch_url = self._proxy_url.replace("{target}", quote(url, safe=""))
        else:
            fetch_url = url
        if self._client is not None:
            r = await self._client.get(fetch_url)
            r.raise_for_status()
            return r.text
        async with httpx.AsyncClient(
            headers=self.HEADERS, timeout=self._timeout, follow_redirects=True
        ) as client:
            r = await client.get(fetch_url)
            r.raise_for_status()
            return r.text

    # ---------- 목록 ----------

    async def fetch_list(self, *, page: int = 1, page_size: int = 10) -> list[NoticePost]:
        params = [
            ("mode", "list"),
            ("srCategoryId1", str(self.category_id)),
            ("srSearchKey", ""),
            ("srSearchVal", ""),
        ]
        if page > 1:
            # 사이트는 article.offset 으로 페이지네이션. offset = (page-1) * 10
            params.append(("article.offset", str((page - 1) * 10)))
            params.append(("articleLimit", "10"))
        url = f"{self.BASE}{self.LIST_PATH}?{urlencode(params, encoding='utf-8')}"

        html = await self._fetch(url)
        soup = BeautifulSoup(html, "lxml")
        items = soup.select("ul.board-list-wrap > li")

        posts: list[NoticePost] = []
        for li in items[:page_size]:
            post = self._li_to_post(li)
            if post is not None:
                posts.append(post)
        return posts

    def _li_to_post(self, li: Tag) -> Optional[NoticePost]:
        title_dt = li.select_one("dt.board-list-content-title")
        if title_dt is None:
            return None

        # 카테고리 ([학사], [졸업평가] 등)
        cat_span = title_dt.select_one("span.c-board-list-category")
        category = self._clean(cat_span.get_text(" ", strip=True)) if cat_span else None
        # 카테고리 양쪽 대괄호 제거
        if category and category.startswith("[") and category.endswith("]"):
            category = category[1:-1]

        # 제목과 링크
        a = title_dt.select_one("a")
        if a is None:
            return None
        title = self._clean(a.get_text(" ", strip=True))
        href = a.get("href", "")
        if not href:
            return None

        # articleNo 추출
        m = re.search(r"[?&]articleNo=(\d+)", href)
        if not m:
            return None
        post_id = m.group(1)

        # 절대 URL
        url = urljoin(f"{self.BASE}{self.LIST_PATH}", href)

        # 부가 정보 (No.X, 작성자, 날짜, 조회수)
        info_dd = li.select_one("dd.board-list-content-info")
        author: Optional[str] = None
        published: Optional[str] = None
        view_count: Optional[str] = None
        post_no: Optional[str] = None
        if info_dd is not None:
            info_lis = info_dd.select("ul > li")
            for info_li in info_lis:
                t = info_li.get_text(" ", strip=True)
                if t.startswith("No."):
                    post_no = t.removeprefix("No.").strip()
                elif self._DATE_RE.match(t):
                    # KST(+09:00)로 ISO 정규화 (시간은 자정으로)
                    published = f"{t}T00:00:00+09:00"
                elif t.startswith("조회수"):
                    span = info_li.select_one("span")
                    view_count = span.get_text(strip=True) if span else None
                else:
                    # 첫 번째로 만나는 비-패턴 텍스트는 작성자/소속
                    if author is None:
                        author = t

        # 풀 제목 (카테고리 prefix 포함)
        full_title = f"[{category}] {title}" if category else title

        return NoticePost(
            site=self.site,
            board=self.board,
            post_id=post_id,
            title=full_title,
            url=url,
            published_at=published,
            author=author,
            category=category,
            summary=None,
            content_html=None,
            cover_image=None,
            raw={
                "post_no": post_no,
                "view_count": view_count,
                "title_no_prefix": title,
            },
        )

    @staticmethod
    def _clean(text: str) -> str:
        return " ".join((text or "").split())

    # ---------- 본문 ----------

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        if not post.url:
            raise ValueError(f"post.url 없음: {post.post_id}")

        html = await self._fetch(post.url)
        soup = BeautifulSoup(html, "lxml")

        # 제목 영역에서 보강
        title = post.title
        published = post.published_at
        author = post.author

        title_wrap = soup.select_one("div.board-view-title-wrap")
        if title_wrap is not None:
            h = title_wrap.select_one("h4")
            if h is not None:
                full = self._clean(h.get_text(" ", strip=True))
                if full:
                    title = full
            etc = title_wrap.select_one("ul.board-etc-wrap")
            if etc is not None:
                for li in etc.select("li"):
                    t = li.get_text(" ", strip=True)
                    if self._DATE_RE.match(t):
                        published = f"{t}T00:00:00+09:00"
                    elif "조회수" in t:
                        continue
                    else:
                        if author is None:
                            author = t

        # 본문 컨테이너
        content_el = soup.select_one("div.fr-view")
        content_html = str(content_el) if content_el is not None else None

        return NoticePost(
            site=self.site,
            board=self.board,
            post_id=post.post_id,
            title=title,
            url=post.url,
            published_at=published,
            author=author,
            category=post.category,
            summary=post.summary,
            content_html=content_html,
            cover_image=post.cover_image,
            raw={**post.raw, "fetched_url": post.url},
        )
