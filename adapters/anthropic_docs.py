from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from .base import BaseAdapter, NoticePost


_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Referer": "https://docs.anthropic.com/en/release-notes/overview",
}


class AnthropicDocsReleaseNotesAdapter(BaseAdapter):
    site = "docs.anthropic.com"
    host = "docs.anthropic.com"
    polite_sleep_min = 3.0
    polite_sleep_max = 6.0

    def __init__(
        self,
        *,
        board: str = "en/release-notes/overview",
        url: str = "https://docs.anthropic.com/en/release-notes/overview",
        timeout: float = 15.0,
    ):
        self.board = board
        self.url = url
        self.timeout = float(timeout)
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "AnthropicDocsReleaseNotesAdapter":
        self._client = httpx.AsyncClient(headers=_HEADERS, timeout=self.timeout, follow_redirects=True)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get_html(self) -> str:
        client = self._client
        if client is None:
            async with httpx.AsyncClient(headers=_HEADERS, timeout=self.timeout, follow_redirects=True) as c:
                r = await c.get(self.url)
        else:
            r = await client.get(self.url)
        r.raise_for_status()
        return r.text

    @staticmethod
    def _date_to_iso(text: str) -> Optional[str]:
        try:
            dt = datetime.strptime(" ".join(text.split()), "%B %d, %Y")
        except ValueError:
            return None
        return dt.replace(tzinfo=timezone.utc).isoformat()

    @staticmethod
    def _title(text: str) -> str:
        text = " ".join(text.split())
        if not text:
            return ""
        for sep in (". ", "; "):
            if sep in text:
                return text.split(sep, 1)[0].strip()[:180]
        return text[:180]

    def _post_id(self, *, date_text: str, text: str, url: Optional[str]) -> str:
        raw = f"{date_text}|{url or ''}|{text}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]

    def _parse_raw_list(self, html: str, *, page_size: int = 30) -> list[NoticePost]:
        soup = BeautifulSoup(html or "", "lxml")
        container = soup.select_one("#content-container")
        if container is None:
            return []

        posts: list[NoticePost] = []
        current_date_text = ""
        current_date_iso: Optional[str] = None
        for node in container.find_all(["h3", "ul"], recursive=False):
            if node.name == "h3":
                current_date_text = node.get_text(" ", strip=True)
                current_date_iso = self._date_to_iso(current_date_text)
                continue
            if node.name != "ul" or not current_date_text:
                continue
            for li in node.find_all("li", recursive=False):
                if not isinstance(li, Tag):
                    continue
                text = li.get_text(" ", strip=True)
                if not text:
                    continue
                a = li.find("a", href=True)
                item_url = urljoin(self.url, a["href"]) if a else f"{self.url}#{self._post_id(date_text=current_date_text, text=text, url=None)}"
                post_id = self._post_id(date_text=current_date_text, text=text, url=item_url)
                posts.append(
                    NoticePost(
                        site=self.site,
                        board=self.board,
                        post_id=post_id,
                        title=self._title(text),
                        url=item_url,
                        published_at=current_date_iso,
                        summary=text,
                        content_html=str(li),
                        raw={"date_text": current_date_text, "source": "anthropic_docs_release_notes"},
                    )
                )
                if len(posts) >= page_size:
                    return posts
        return posts

    async def fetch_list(self, *, page: int = 1, page_size: int = 10) -> list[NoticePost]:
        if page > 1:
            return []
        html = await self._get_html()
        posts = self._parse_raw_list(html, page_size=page_size)
        await self.polite_sleep()
        return posts

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        return replace(post, content_html=post.content_html or post.summary)
