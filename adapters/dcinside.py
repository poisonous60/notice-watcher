"""디시인사이드 마이너 갤러리 어댑터.

probe 결과:
- httpx S1.H2 (UA만)으로 200 OK. Cloudflare 없음.
- robots.txt가 Crawl-Delay: 30 명시 → polite_sleep_min/max = 30/35.
- 목록 selector: tr.ub-content.us-post (일반 글), tr.ub-content (공지/AD = 글번호 '-')
- 글 URL: https://gall.dcinside.com/mgallery/board/view/?id={갤}&no={번호}&page=1
- 본문 selector: div.write_div (또는 .writing_view_box / .gallview_contents)
- 글 헤더 제목: div.gallview_head .title_subject

(주의) 모바일 앱 API(`m.dcinside.com/api/gall_list.php`)는 2026-05 시점 404로 폐기됨.
PC 웹 HTML이 현재 검증된 유일한 안정 진입점.

사용:
    async with DCInsideMGalleryAdapter(gallery_id="endfield") as a:
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


class DCInsideMGalleryAdapter(BaseAdapter):
    site = "dcinside.mgallery"
    host = "gall.dcinside.com"
    BASE = "https://gall.dcinside.com"
    LIST_PATH = "/mgallery/board/lists/"
    VIEW_PATH = "/mgallery/board/view/"

    # robots.txt Crawl-Delay 30 준수.
    polite_sleep_min = 30.0
    polite_sleep_max = 35.0

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    HEADERS = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://gall.dcinside.com/",
    }

    _DATE_FULL_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

    def __init__(
        self,
        *,
        gallery_id: str,
        include_notices: bool = True,
        list_params: Optional[dict] = None,
        timeout: float = 15.0,
    ):
        self.gallery_id = gallery_id
        self.board = gallery_id
        self.include_notices = include_notices
        # 목록 URL 추가 필터 (exception_mode=recommend 개념글 / s_type+s_keyword 검색 /
        # sort_type 정렬 / search_head 말머리 …). 빈 dict 면 전체글.
        self.list_params = dict(list_params or {})
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "DCInsideMGalleryAdapter":
        self._client = httpx.AsyncClient(
            headers=self.HEADERS, timeout=self._timeout, follow_redirects=True
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get_text(self, url: str) -> str:
        if self._client is not None:
            r = await self._client.get(url)
            r.raise_for_status()
            return r.text
        async with httpx.AsyncClient(
            headers=self.HEADERS, timeout=self._timeout, follow_redirects=True
        ) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.text

    # ---------- 목록 ----------

    async def fetch_list(self, *, page: int = 1, page_size: int = 50) -> list[NoticePost]:
        params: list[tuple[str, str]] = [("id", self.gallery_id)]
        for k in sorted(self.list_params):
            params.append((k, self.list_params[k]))
        if page > 1:
            params.append(("page", str(page)))
        url = f"{self.BASE}{self.LIST_PATH}?{urlencode(params, encoding='utf-8')}"

        html = await self._get_text(url)
        soup = BeautifulSoup(html, "lxml")
        rows = soup.select("tr.ub-content")

        posts: list[NoticePost] = []
        for row in rows:
            classes = set(row.get("class") or [])
            no_cell = row.select_one("td.gall_num")
            if no_cell is None:
                continue
            no_text = no_cell.get_text(strip=True)

            is_notice_row = "us-post" not in classes  # 글번호가 '-' 인 공지/광고 행
            if is_notice_row and not self.include_notices:
                continue
            if is_notice_row and not no_text.isdigit():
                # 글번호 없는 공지/광고는 sticky '공지' 행. fetch는 가능
                # td.gall_tit a 의 href에서 no 추출
                a = row.select_one("td.gall_tit a")
                href = a.get("href", "") if a else ""
                m = re.search(r"[?&]no=(\d+)", href)
                if not m:
                    continue
                post_id = m.group(1)
            else:
                if not no_text.isdigit():
                    continue
                post_id = no_text

            posts.append(self._row_to_post(row, post_id, classes))
            if len(posts) >= page_size:
                break

        return posts

    def _row_to_post(self, row: Tag, post_id: str, classes: set[str]) -> NoticePost:
        title_cell = row.select_one("td.gall_tit")
        title_a = row.select_one("td.gall_tit a")
        subject_cell = row.select_one("td.gall_subject")
        writer_cell = row.select_one("td.gall_writer")
        date_cell = row.select_one("td.gall_date")
        count_cell = row.select_one("td.gall_count")
        recommend_cell = row.select_one("td.gall_recommend")

        title = ""
        if title_a is not None:
            title = self._clean(title_a.get_text(" ", strip=True))
        elif title_cell is not None:
            title = self._clean(title_cell.get_text(" ", strip=True))

        href = title_a.get("href", "") if title_a else ""
        url = urljoin(self.BASE, href) if href else f"{self.BASE}{self.VIEW_PATH}?id={self.gallery_id}&no={post_id}&page=1"

        author = writer_cell.get_text(strip=True) if writer_cell else None

        published = None
        if date_cell is not None:
            # title 속성에 'YYYY-MM-DD HH:MM:SS' 풀 timestamp가 있을 수 있음. 없으면 텍스트.
            attr = date_cell.get("title")
            if attr and self._DATE_FULL_RE.match(attr):
                published = attr.replace(" ", "T") + "+09:00"  # 한국 시간으로 가정
            else:
                published = date_cell.get_text(strip=True) or None

        category = subject_cell.get_text(strip=True) if subject_cell else None
        is_notice_row = "us-post" not in classes

        return NoticePost(
            site=self.site,
            board=self.gallery_id,
            post_id=post_id,
            title=title,
            url=url,
            published_at=published,
            author=author,
            category=category,
            summary=None,
            content_html=None,
            cover_image=None,
            raw={
                "row_classes": sorted(classes),
                "is_notice_row": is_notice_row,
                "view_count": count_cell.get_text(strip=True) if count_cell else None,
                "recommend_count": recommend_cell.get_text(strip=True) if recommend_cell else None,
            },
        )

    @staticmethod
    def _clean(text: str) -> str:
        return " ".join((text or "").split())

    # ---------- 본문 ----------

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        url = post.url or (
            f"{self.BASE}{self.VIEW_PATH}?id={self.gallery_id}&no={post.post_id}&page=1"
        )
        html = await self._get_text(url)
        soup = BeautifulSoup(html, "lxml")

        # 제목/작성자/날짜 보강
        title = post.title
        author = post.author
        published = post.published_at

        head = soup.select_one("div.gallview_head, .view_content_wrap .gallview_head")
        if head is not None:
            t_el = head.select_one(".title_subject, .gall_title")
            if t_el and not title:
                title = self._clean(t_el.get_text(" ", strip=True))
            w_el = head.select_one(".nickname, .gall_writer .nickname")
            if w_el:
                author = w_el.get_text(strip=True)
            d_el = head.select_one(".gall_date, .date")
            if d_el:
                attr = d_el.get("title")
                if attr and self._DATE_FULL_RE.match(attr):
                    published = attr.replace(" ", "T") + "+09:00"
                else:
                    published = d_el.get_text(strip=True) or published

        # 본문 컨테이너 (probe로 검증된 셀렉터들)
        content_el = (
            soup.select_one("div.write_div")
            or soup.select_one(".writing_view_box")
            or soup.select_one(".gallview_contents")
        )
        content_html = str(content_el) if content_el is not None else None

        return NoticePost(
            site=self.site,
            board=self.gallery_id,
            post_id=post.post_id,
            title=title,
            url=url,
            published_at=published,
            author=author,
            category=post.category,
            summary=post.summary,
            content_html=content_html,
            cover_image=post.cover_image,
            raw={**post.raw, "fetched_url": url},
        )
