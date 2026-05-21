"""AniList public GraphQL adapter.

AniList search pages are Vue-rendered shells. The stable public surface for
media lists is the GraphQL endpoint at https://graphql.anilist.co.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Optional

import httpx

from .base import BaseAdapter, NoticePost


_QUERY = """
query ($page: Int, $perPage: Int, $type: MediaType, $sort: [MediaSort]) {
  Page(page: $page, perPage: $perPage) {
    media(type: $type, sort: $sort) {
      id
      title { userPreferred romaji english native }
      siteUrl
      description
      startDate { year month day }
      format
      status
      averageScore
      popularity
      coverImage { large }
    }
  }
}
"""

_AIRING_QUERY = """
query ($page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    airingSchedules(sort: TIME, notYetAired: true) {
      id
      episode
      airingAt
      media {
        id
        title { userPreferred romaji english native }
        siteUrl
        description
        format
        status
        averageScore
        popularity
        coverImage { large }
      }
    }
  }
}
"""


class AniListMediaAdapter(BaseAdapter):
    polite_sleep_min = 3.0
    polite_sleep_max = 6.0

    def __init__(
        self,
        *,
        media_type: str = "ANIME",
        board: str = "search/anime",
        sort: str = "SCORE_DESC",
        timeout: float = 15.0,
    ):
        self.media_type = (media_type or "ANIME").upper()
        self.board = board or f"search/{self.media_type.lower()}"
        self.sort = sort or "SCORE_DESC"
        self.site = "anilist.co"
        self.host = "anilist.co"
        self.timeout = float(timeout)
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "AniListMediaAdapter":
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": "notice-watcher/1.0 (+https://github.com/poisonous60/notice-watcher)",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=self.timeout,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _post_graphql(self, variables: dict) -> dict:
        payload = {"query": _QUERY, "variables": variables}
        if self._client is None:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                r = await client.post("https://graphql.anilist.co", json=payload)
        else:
            r = await self._client.post("https://graphql.anilist.co", json=payload)
        r.raise_for_status()
        data = r.json()
        if data.get("errors"):
            raise RuntimeError(f"AniList GraphQL errors: {data['errors']!r}")
        return data

    async def fetch_list(self, *, page: int = 1, page_size: int = 10) -> list[NoticePost]:
        per_page = max(1, min(int(page_size or 10), 50))
        data = await self._post_graphql({
            "page": max(1, int(page or 1)),
            "perPage": per_page,
            "type": self.media_type,
            "sort": [self.sort],
        })
        media = (((data.get("data") or {}).get("Page") or {}).get("media") or [])
        posts: list[NoticePost] = []
        for item in media:
            if not isinstance(item, dict) or item.get("id") is None:
                continue
            posts.append(self._to_post(item, include_body=False))
        await self.polite_sleep()
        return posts

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        item = post.raw.get("_item") if isinstance(post.raw, dict) else None
        if isinstance(item, dict):
            return self._to_post(item, fallback=post, include_body=True)
        return post

    def _to_post(
        self,
        item: dict,
        *,
        fallback: Optional[NoticePost] = None,
        include_body: bool,
    ) -> NoticePost:
        pid = str(item.get("id") or (fallback.post_id if fallback else ""))
        title = self._title(item.get("title") or {}) or (fallback.title if fallback else "")
        url = item.get("siteUrl") or f"https://anilist.co/{self.media_type.lower()}/{pid}"
        published = self._date(item.get("startDate") or {}) or (fallback.published_at if fallback else None)
        summary = self._summary(item)
        content = self._content(item, url=url) if include_body else (fallback.content_html if fallback else None)
        cover = ((item.get("coverImage") or {}).get("large") or None)
        return NoticePost(
            site=self.site,
            board=self.board,
            post_id=pid,
            title=title,
            url=url,
            published_at=published,
            author=None,
            category=item.get("format") or item.get("status"),
            summary=summary,
            content_html=content,
            cover_image=cover,
            raw={"_strategy": "anilist_graphql", "_item": item},
        )

    @staticmethod
    def _title(title: dict) -> str:
        for key in ("userPreferred", "english", "romaji", "native"):
            value = title.get(key)
            if value:
                return str(value)
        return ""

    @staticmethod
    def _date(start: dict) -> Optional[str]:
        year = start.get("year")
        if not year:
            return None
        month = int(start.get("month") or 1)
        day = int(start.get("day") or 1)
        return f"{int(year):04d}-{month:02d}-{day:02d}"

    @staticmethod
    def _summary(item: dict) -> Optional[str]:
        bits = []
        if item.get("status"):
            bits.append(str(item["status"]))
        if item.get("format"):
            bits.append(str(item["format"]))
        if item.get("averageScore") is not None:
            bits.append(f"score {item['averageScore']}")
        if item.get("popularity") is not None:
            bits.append(f"popularity {item['popularity']}")
        return " / ".join(bits) if bits else None

    def _content(self, item: dict, *, url: str) -> str:
        parts = []
        desc = (item.get("description") or "").strip()
        if desc:
            parts.append(desc)
        summary = self._summary(item)
        if summary:
            parts.append(f"<p>{escape(summary)}</p>")
        parts.append(f'<p><a href="{escape(url, quote=True)}">AniList에서 보기</a></p>')
        return "\n".join(parts)


class AniListAiringAdapter(BaseAdapter):
    polite_sleep_min = 3.0
    polite_sleep_max = 6.0

    def __init__(self, *, board: str = "airing", timeout: float = 15.0):
        self.site = "anichart.net"
        self.board = board or "airing"
        self.host = "anichart.net"
        self.timeout = float(timeout)
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "AniListAiringAdapter":
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": "notice-watcher/1.0 (+https://github.com/poisonous60/notice-watcher)",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Referer": "https://anichart.net/airing",
            },
            timeout=self.timeout,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _post_graphql(self, variables: dict) -> dict:
        payload = {"query": _AIRING_QUERY, "variables": variables}
        if self._client is None:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                r = await client.post("https://graphql.anilist.co", json=payload)
        else:
            r = await self._client.post("https://graphql.anilist.co", json=payload)
        r.raise_for_status()
        data = r.json()
        if data.get("errors"):
            raise RuntimeError(f"AniList GraphQL errors: {data['errors']!r}")
        return data

    async def fetch_list(self, *, page: int = 1, page_size: int = 10) -> list[NoticePost]:
        per_page = max(1, min(int(page_size or 10), 50))
        data = await self._post_graphql({"page": max(1, int(page or 1)), "perPage": per_page})
        schedules = (((data.get("data") or {}).get("Page") or {}).get("airingSchedules") or [])
        posts: list[NoticePost] = []
        for item in schedules:
            if not isinstance(item, dict) or item.get("id") is None:
                continue
            media = item.get("media") if isinstance(item.get("media"), dict) else {}
            if not media:
                continue
            posts.append(self._to_post(item, media=media, include_body=False))
        await self.polite_sleep()
        return posts

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        item = post.raw.get("_item") if isinstance(post.raw, dict) else None
        media = post.raw.get("_media") if isinstance(post.raw, dict) else None
        if isinstance(item, dict) and isinstance(media, dict):
            return self._to_post(item, media=media, fallback=post, include_body=True)
        return post

    def _to_post(
        self,
        item: dict,
        *,
        media: dict,
        fallback: Optional[NoticePost] = None,
        include_body: bool,
    ) -> NoticePost:
        media_id = str(media.get("id") or "")
        episode = item.get("episode")
        pid = str(item.get("id") or f"{media_id}:{episode or ''}")
        title = AniListMediaAdapter._title(media.get("title") or {}) or (fallback.title if fallback else "")
        if episode is not None:
            title = f"{title} #{episode}"
        url = media.get("siteUrl") or (f"https://anilist.co/anime/{media_id}" if media_id else None)
        published = self._airing_at(item.get("airingAt")) or (fallback.published_at if fallback else None)
        summary = AniListMediaAdapter._summary(media)
        content = self._content(media, url=url) if include_body and url else (fallback.content_html if fallback else None)
        cover = ((media.get("coverImage") or {}).get("large") or None)
        return NoticePost(
            site=self.site,
            board=self.board,
            post_id=pid,
            title=title,
            url=url,
            published_at=published,
            author=None,
            category=media.get("format") or media.get("status"),
            summary=summary,
            content_html=content,
            cover_image=cover,
            raw={"_strategy": "anilist_airing_graphql", "_item": item, "_media": media},
        )

    @staticmethod
    def _airing_at(value: object) -> Optional[str]:
        try:
            ts = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    @staticmethod
    def _content(media: dict, *, url: str) -> str:
        parts = []
        desc = (media.get("description") or "").strip()
        if desc:
            parts.append(desc)
        summary = AniListMediaAdapter._summary(media)
        if summary:
            parts.append(f"<p>{escape(summary)}</p>")
        parts.append(f'<p><a href="{escape(url, quote=True)}">AniList에서 보기</a></p>')
        return "\n".join(parts)
