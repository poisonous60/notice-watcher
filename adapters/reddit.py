"""Reddit 서브레딧 어댑터 — 공개 JSON 엔드포인트(`.json`) 사용.

Reddit 은 거의 모든 페이지 URL 뒤에 `.json` 을 붙이면 같은 데이터를 JSON 으로 준다.
  목록: https://www.reddit.com/r/{subreddit}/{sort}.json?limit=&raw_json=1
        sort ∈ {hot, new, top, rising};  top 은 `&t=hour|day|week|month|year|all` 로 기간 지정.
        응답: {"kind":"Listing","data":{"after":..,"children":[{"kind":"t3","data":{...글...}}, ...]}}
  본문: https://www.reddit.com{permalink}.json?raw_json=1
        응답이 **배열** [postListing, commentListing] — 글은 [0]["data"]["children"][0]["data"].
        self 글이면 `selftext_html`(이미 렌더된 HTML), 링크/이미지/갤러리 글이면 본문 대신 그 링크·미디어를 간단한 HTML 로 합성.

정책:
  - User-Agent 헤더 없으면 429. 여기선 평범한 브라우저 UA + polite_sleep + 429 시 백오프 재시도만 한다(로그인/우회 없음).
  - reddit robots.txt 는 `User-agent: * / Disallow: /` (HTML 스크레이핑 전면 금지) 라고 명시한다. `.json` 은 구
    reddit API 표면이고 RSS 리더 등 서드파티가 이 방식으로 콘텐츠를 읽지만, 정책상 회색지대임을 알고 쓴다(저빈도 개인용).
  - 비공개/quarantine 서브레딧이면 목록 API 가 403 → 빈 목록 반환(우회 안 함).

kwargs:
  subreddit          : "CosmicPrincessKaguya" (또는 "r/CosmicPrincessKaguya")
  sort               : "new"(기본) | "hot" | "top" | "rising"
  time_filter        : sort=="top" 일 때 기간. "day"(기본) | "hour" | "week" | "month" | "year" | "all"
  flair              : 주어지면 link_flair_text 가 이 값(대소문자 무시)인 글만 — 'Fan Art' 같은 플레어로 거르면 '창작탭' 효과.
  include_stickied   : 고정(stickied)글 포함 여부(기본 True; 공지처럼 목록 앞에 옴).

    async with RedditAdapter(subreddit="CosmicPrincessKaguya", sort="new") as a:
        posts = await a.fetch_list()
        full = await a.fetch_article(posts[0])
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from html import escape
from typing import Optional

import httpx

from .base import BaseAdapter, NoticePost


_VALID_SORTS = {"hot", "new", "top", "rising"}
_VALID_TIMES = {"hour", "day", "week", "month", "year", "all"}
_IMG_EXTS = ("jpg", "jpeg", "png", "gif", "gifv", "webp")


class RedditAdapter(BaseAdapter):
    site = "reddit.com"
    host = "reddit.com"
    # robots.txt 에 Crawl-Delay 명시 없음 → 보수치(구 reddit 권고 ≈ 2초보다 넉넉히).
    polite_sleep_min = 4.0
    polite_sleep_max = 8.0

    BASE = "https://www.reddit.com"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    HEADERS = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }

    def __init__(
        self,
        *,
        subreddit: str,
        sort: str = "new",
        time_filter: str = "day",
        flair: Optional[str] = None,
        include_stickied: bool = True,
        timeout: float = 15.0,
    ):
        sub = str(subreddit or "").strip().strip("/")
        if sub.lower().startswith("r/"):
            sub = sub[2:]
        self.subreddit = sub
        self.sort = sort if sort in _VALID_SORTS else "new"
        self.time_filter = time_filter if time_filter in _VALID_TIMES else "day"
        self.flair = (flair or "").strip() or None
        self.include_stickied = bool(include_stickied)
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

        parts = [self.subreddit]
        if self.sort != "new":
            parts.append(self.sort + (f":{self.time_filter}" if self.sort == "top" else ""))
        if self.flair:
            parts.append(f"flair={self.flair}")
        self.board = "/".join(parts)

    async def __aenter__(self) -> "RedditAdapter":
        self._client = httpx.AsyncClient(headers=self.HEADERS, timeout=self._timeout, follow_redirects=True)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ---------- HTTP ----------

    async def _get_json(self, url: str, *, params: Optional[dict] = None):
        async def _do(client: httpx.AsyncClient):
            last: Optional[httpx.Response] = None
            for attempt in range(3):
                r = await client.get(url, params=params)
                last = r
                if r.status_code == 429:
                    await asyncio.sleep(5 * (attempt + 1))  # rate-limit 백오프(우회 아님, 그냥 대기)
                    continue
                r.raise_for_status()
                return r.json()
            assert last is not None
            last.raise_for_status()
            return last.json()

        if self._client is not None:
            return await _do(self._client)
        async with httpx.AsyncClient(headers=self.HEADERS, timeout=self._timeout, follow_redirects=True) as c:
            return await _do(c)

    def _listing_url(self) -> str:
        sort = self.sort if self.sort in _VALID_SORTS else "new"
        return f"{self.BASE}/r/{self.subreddit}/{sort}.json"

    def _permalink_url(self, permalink: Optional[str]) -> Optional[str]:
        if not permalink:
            return None
        return permalink if permalink.startswith("http") else self.BASE + permalink

    @staticmethod
    def _ts_to_iso(ts) -> Optional[str]:
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            return None

    def _matches_flair(self, d: dict) -> bool:
        if not self.flair:
            return True
        return (d.get("link_flair_text") or "").strip().lower() == self.flair.lower()

    # ---------- 목록 ----------

    async def fetch_list(self, *, page: int = 1, page_size: int = 25) -> list[NoticePost]:
        # Reddit 은 cursor(after) 페이징이라 page>1 은 지원하지 않음 — 워처는 1페이지만 폴링한다.
        if page and page > 1:
            return []
        limit = max(1, min(int(page_size or 25), 100))
        params = {"limit": limit, "raw_json": 1}
        if self.sort == "top":
            params["t"] = self.time_filter
        try:
            data = await self._get_json(self._listing_url(), params=params)
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code in (403, 404, 451):
                return []  # 비공개/없음/차단 — 우회하지 않고 빈 목록
            raise
        children = ((data or {}).get("data") or {}).get("children") or []
        posts: list[NoticePost] = []
        seen: set[str] = set()
        for c in children:
            if c.get("kind") != "t3":
                continue
            d = c.get("data") or {}
            if not self.include_stickied and d.get("stickied"):
                continue
            if not self._matches_flair(d):
                continue
            pid = str(d.get("id") or "")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            posts.append(self._to_post(d, content_html=None))
        return posts

    # ---------- 본문 ----------

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        permalink = (post.raw or {}).get("permalink") or ""
        base_url = self._permalink_url(permalink) or post.url
        d: Optional[dict] = None
        if base_url:
            stripped = base_url.rstrip("/")
            json_url = stripped if stripped.endswith(".json") else stripped + "/.json"
            try:
                payload = await self._get_json(json_url, params={"raw_json": 1})
                if isinstance(payload, list) and payload:
                    ch = ((payload[0] or {}).get("data") or {}).get("children") or []
                    if ch and ch[0].get("data"):
                        d = ch[0]["data"]
            except httpx.HTTPStatusError:
                pass  # 본문 응답 실패 → 목록에서 알던 것만으로 최소 본문 구성
        if d is None:
            r = post.raw or {}
            d = {
                "id": post.post_id, "title": post.title, "permalink": permalink,
                "is_self": r.get("is_self"), "url_overridden_by_dest": r.get("url_overridden_by_dest"),
                "link_flair_text": r.get("link_flair_text"),
            }
        return self._to_post(d, content_html=self._compose_body(d, fallback=post), fallback=post)

    # ---------- 변환 ----------

    def _to_post(self, d: dict, *, content_html: Optional[str], fallback: Optional[NoticePost] = None) -> NoticePost:
        fb_raw = (fallback.raw if fallback else {}) or {}
        pid = str(d.get("id") or (fallback.post_id if fallback else "") or "")
        permalink = d.get("permalink") or fb_raw.get("permalink") or ""
        return NoticePost(
            site=self.site,
            board=self.board,
            post_id=pid,
            title=(d.get("title") or (fallback.title if fallback else "") or ""),
            url=self._permalink_url(permalink) or (fallback.url if fallback else None),
            published_at=self._ts_to_iso(d.get("created_utc")) or (fallback.published_at if fallback else None),
            author=(d.get("author") or None) or (fallback.author if fallback else None),
            category=(d.get("link_flair_text") or None) or (fallback.category if fallback else None),
            summary=None,
            content_html=content_html if content_html is not None else (fallback.content_html if fallback else None),
            cover_image=self._cover(d) or (fallback.cover_image if fallback else None),
            raw={
                "permalink": permalink,
                "stickied": bool(d.get("stickied")),
                "is_self": bool(d.get("is_self")),
                "over_18": bool(d.get("over_18")),
                "spoiler": bool(d.get("spoiler")),
                "link_flair_text": d.get("link_flair_text"),
                "score": d.get("score"),
                "num_comments": d.get("num_comments"),
                "upvote_ratio": d.get("upvote_ratio"),
                "domain": d.get("domain"),
                "post_hint": d.get("post_hint"),
                "url_overridden_by_dest": d.get("url_overridden_by_dest"),
                "subreddit": d.get("subreddit"),
            },
        )

    @staticmethod
    def _cover(d: dict) -> Optional[str]:
        imgs = (d.get("preview") or {}).get("images") or []
        if imgs:
            src = (imgs[0] or {}).get("source") or {}
            if src.get("url"):
                return src["url"]
        th = d.get("thumbnail") or ""
        if isinstance(th, str) and th.startswith("http"):
            return th
        dest = d.get("url_overridden_by_dest") or ""
        if dest and dest.split("?", 1)[0].rsplit(".", 1)[-1].lower() in _IMG_EXTS:
            return dest
        return None

    def _compose_body(self, d: dict, *, fallback: Optional[NoticePost] = None) -> str:
        parts: list[str] = []
        sh = d.get("selftext_html")
        if sh:
            parts.append(sh)  # raw_json=1 → 이미 디코드된 HTML (md 래퍼 포함)
        dest = d.get("url_overridden_by_dest") or ""
        if dest and not d.get("is_self"):
            if dest.split("?", 1)[0].rsplit(".", 1)[-1].lower() in _IMG_EXTS:
                parts.append(f'<p><img src="{escape(dest, quote=True)}" alt=""></p>')
            else:
                parts.append(f'<p><a href="{escape(dest, quote=True)}">{escape(dest)}</a></p>')
        if d.get("is_gallery") and isinstance(d.get("media_metadata"), dict):
            for meta in d["media_metadata"].values():
                s = (meta or {}).get("s") or {}
                u = s.get("u") or s.get("gif")
                if u:
                    parts.append(f'<p><img src="{escape(u, quote=True)}" alt=""></p>')
        if not parts:
            link = self._permalink_url(d.get("permalink") or "") or (fallback.url if fallback else "") or ""
            parts.append(f'<p>(본문 없음 — <a href="{escape(link, quote=True)}">Reddit 에서 보기</a>)</p>')
        return "\n".join(parts)
