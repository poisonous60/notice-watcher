"""다음(Daum) 카페 모바일 게시판 어댑터.

probe 결과 (`m.cafe.daum.net/<cafe>/<board>?boardType=`):
- 정적 httpx GET 으로 200 OK. Cloudflare/JS-gate 없음.
- **글 목록이 정적 HTML 의 <li> 에는 안 들어있다** — `<li><a href="javascript:" class="link_cafe make-list-uri">` 라서
  자동 파이프라인(httpx_html/playwright_html)이 post_id/url 을 못 뽑는다. 대신 페이지 안에 인라인 JS 로:
      var articles = [];
      articles.push({ dataid: 692, fldid: "Z4os", title: "...", writerNickname: "...",
                      articleElapsedTime: "26.05.08", viewCount: Number("2482"),
                      commentCount: Number("0"), headCont: "공지사항", thumbnailImageUrl: "...", ... });
      ...
  이 블록을 regex 로 파싱한다 (JS 라 json.loads 불가 — 필드별 정규식).
- 글 본문 `m.cafe.daum.net/<cafe>/<board>/<dataid>` 는 정적 HTML, 본문 컨테이너 `div#article.tx-content-container`,
  제목 `h3.tit_subject`(말머리 `[..]` 접두어 포함 → `span.article_title` 이 순수 제목), 날짜 `span.num_subject`.
- 페이지네이션: 모바일 카페는 무한스크롤(AJAX) — 정적 페이지는 1페이지(~20건)만. 공지 게시판엔 충분 → page>1 은 무시.
- 비공개/등급제한 카페·게시판이면 401/403 → 본문 비워서 반환(우회 안 함).

사용:
    async with DaumCafeAdapter(cafe_name="umamusume-kor", board_id="Z4os") as a:
        posts = await a.fetch_list(page=1)
        full = await a.fetch_article(posts[0])
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from .base import BaseAdapter, NoticePost

_KST = timezone(timedelta(hours=9))

# `articles.push({ ... })` 한 블록 (객체 안에 중첩 {} 없음 — 첫 `}` 가 닫는 괄호).
_PUSH_RE = re.compile(r"articles\.push\(\s*\{(.*?)\}\s*\)", re.DOTALL)
# 비공개/등급제한 → 본문 안 채움 (우회 안 함)
_SKIP_ARTICLE_STATUS = {401, 403}


def _js_str(block: str, key: str) -> Optional[str]:
    """`key: "..."` 의 값을 JS 문자열 이스케이프 해석해서 반환."""
    m = re.search(rf'\b{re.escape(key)}\s*:\s*"((?:[^"\\]|\\.)*)"', block)
    if not m:
        return None
    raw = m.group(1)
    try:
        return json.loads('"' + raw + '"')  # JS 문자열 이스케이프 ⊂ JSON
    except json.JSONDecodeError:
        return raw.replace('\\"', '"').replace("\\/", "/").replace("\\\\", "\\")


def _js_int(block: str, key: str) -> Optional[int]:
    """`key: 692` 또는 `key: Number("2482")` 의 정수값."""
    m = re.search(rf'\b{re.escape(key)}\s*:\s*(?:Number\(\s*"(\d+)"\s*\)|(\d+))', block)
    if not m:
        return None
    return int(m.group(1) or m.group(2))


def _elapsed_to_iso(s: Optional[str]) -> Optional[str]:
    """다음 카페 목록의 작성시간 표기 → ISO8601(KST). `26.05.08` → date, `12:34` → 오늘+시각. 파싱 안 되거나 비정상 값이면 None."""
    if not s:
        return None
    s = s.strip()
    m = re.match(r"^(\d{2})\.(\d{2})\.(\d{2})$", s)
    if m:
        try:
            d = datetime.strptime(s, "%y.%m.%d").date()  # 자릿수만 맞고 13월/32일 같은 값은 여기서 걸러짐
        except ValueError:
            return None
        return f"{d.isoformat()}T00:00:00+09:00"
    m = re.match(r"^(\d{1,2}):(\d{2})$", s)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        if hh > 23 or mm > 59:
            return None
        today = datetime.now(_KST).date()
        return f"{today.isoformat()}T{hh:02d}:{mm:02d}:00+09:00"
    return None


def _clean(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    t = " ".join(text.split())
    return t or None


class DaumCafeAdapter(BaseAdapter):
    site = "m.cafe.daum.net"
    host = "m.cafe.daum.net"
    BASE = "https://m.cafe.daum.net"
    # m.cafe.daum.net/robots.txt 에 Crawl-Delay 없음(Disallow 도 /_* 류만 — 우리가 치는 /<cafe>/<board>·/<cafe>/<board>/<id> 와 무관)
    # → BaseAdapter 기본값(polite_sleep 2~5s) 그대로. 게다가 목록은 page 1 만 받고(무한스크롤) 폴링 빈도도 낮음.

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        *,
        cafe_name: str,
        board_id: str,
        timeout: float = 15.0,
        proxy_url: Optional[str] = None,
    ):
        """cafe_name: URL 의 카페 식별자(예 'umamusume-kor'). board_id: 게시판(fldid, 예 'Z4os').
        proxy_url: '{target}' 자리에 URL-encoded 원본을 끼우는 프록시 베이스(없으면 직접)."""
        self.cafe_name = cafe_name
        self.board_id = board_id
        self.board = board_id
        self._timeout = timeout
        self._proxy_url = proxy_url
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def _headers(self) -> dict:
        return {
            "User-Agent": self.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": f"{self.BASE}/{self.cafe_name}/{self.board_id}?boardType=",
        }

    async def __aenter__(self) -> "DaumCafeAdapter":
        self._client = httpx.AsyncClient(headers=self._headers, timeout=self._timeout, follow_redirects=True)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get(self, url: str) -> httpx.Response:
        fetch_url = self._proxy_url.replace("{target}", quote(url, safe="")) if self._proxy_url else url
        if self._client is not None:
            return await self._client.get(fetch_url)
        async with httpx.AsyncClient(headers=self._headers, timeout=self._timeout, follow_redirects=True) as c:
            return await c.get(fetch_url)

    # ---------- 목록 ----------

    async def fetch_list(self, *, page: int = 1, page_size: int = 10) -> list[NoticePost]:
        if page > 1:
            return []  # 모바일 카페는 무한스크롤 — 정적 페이지는 1페이지만(공지 게시판엔 충분)
        url = f"{self.BASE}/{self.cafe_name}/{self.board_id}?boardType="
        r = await self._get(url)
        r.raise_for_status()
        html = r.text

        posts: list[NoticePost] = []
        seen: set[str] = set()
        for m in _PUSH_RE.finditer(html):
            block = m.group(1)
            dataid = _js_int(block, "dataid")
            if dataid is None:
                continue
            pid = str(dataid)
            if pid in seen:
                continue
            seen.add(pid)
            fldid = _js_str(block, "fldid") or self.board_id
            title = _clean(_js_str(block, "title")) or ""
            head = _clean(_js_str(block, "headCont"))
            full_title = f"[{head}]{title}" if head else title
            posts.append(NoticePost(
                site=self.site,
                board=self.board,
                post_id=pid,
                title=full_title,
                url=f"{self.BASE}/{self.cafe_name}/{fldid}/{dataid}",
                published_at=_elapsed_to_iso(_js_str(block, "articleElapsedTime")),
                author=_clean(_js_str(block, "writerNickname")),
                category=head,
                summary=None,
                content_html=None,
                cover_image=_js_str(block, "thumbnailImageUrl"),
                raw={
                    "fldid": fldid,
                    "view_count": _js_int(block, "viewCount"),
                    "comment_count": _js_int(block, "commentCount"),
                    "title_no_prefix": title,
                },
            ))
            if len(posts) >= page_size:
                break
        return posts

    # ---------- 본문 ----------

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        # fetch_list 가 만든 post 면 post.url 이 항상 채워져 있다. 외부에서 url 없이 넘긴 post 를 대비한 폴백
        # (raw["fldid"] 도 fetch_list 가 항상 넣지만, 그것도 없으면 board_id).
        url = post.url or f"{self.BASE}/{self.cafe_name}/{post.raw.get('fldid', self.board_id)}/{post.post_id}"
        r = await self._get(url)
        if r.status_code in _SKIP_ARTICLE_STATUS:
            return self._with(post, content_html=None, url=url,
                              raw_note={"fetch_status": r.status_code, "fetch_note": "비공개/등급제한 — 본문 생략"})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")

        title = post.title
        category = post.category
        h3 = soup.select_one("h3.tit_subject")
        if h3 is not None:
            full = _clean(h3.get_text(" ", strip=True))
            if full:
                title = full
            mcat = re.match(r"^\[(.*?)\]", full or "")
            if mcat:
                category = mcat.group(1)

        published = post.published_at
        author = post.author
        subj = soup.select_one("span.txt_subject")
        if subj is not None:
            nums = subj.select("span.num_subject")
            if nums:
                iso = _elapsed_to_iso(nums[0].get_text(strip=True))
                if iso:
                    published = iso
            # `작성자CM게이트|작성시간26.05.08|조회수2,482` — sr_only 라벨 제거 후 첫 토큰이 작성자
            txt = subj.get_text("|", strip=True)
            mw = re.search(r"작성자\|?([^|]+)", txt)
            if mw and not author:
                author = _clean(mw.group(1))

        content_el = (soup.select_one("div#article.tx-content-container")
                      or soup.select_one("div#article")
                      or soup.select_one("div.tx-content-container"))
        content_html = str(content_el) if content_el is not None else None

        return self._with(post, content_html=content_html, url=url,
                          overrides={"title": title, "category": category,
                                     "published_at": published, "author": author},
                          raw_note={"fetched_url": url})

    @staticmethod
    def _with(post: NoticePost, *, content_html, url, overrides: Optional[dict] = None,
              raw_note: Optional[dict] = None) -> NoticePost:
        ov = overrides or {}
        return NoticePost(
            site=post.site,
            board=post.board,
            post_id=post.post_id,
            title=str(ov.get("title", post.title) or ""),
            url=url if url is not None else post.url,
            published_at=ov.get("published_at", post.published_at),
            author=ov.get("author", post.author),
            category=ov.get("category", post.category),
            summary=post.summary,
            content_html=content_html,
            cover_image=post.cover_image,
            raw={**post.raw, **(raw_note or {})},
        )
