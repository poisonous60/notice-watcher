from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Optional

import httpx
from bs4 import BeautifulSoup, Tag

from .base import BaseAdapter, NoticePost


_FEED_URL = "https://cloud.google.com/feeds/gcp-release-notes.xml"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "application/atom+xml, application/xml, text/xml, */*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}


class GoogleCloudReleaseNotesAdapter(BaseAdapter):
    site = "cloud.google.com"
    host = "cloud.google.com"
    polite_sleep_min = 3.0
    polite_sleep_max = 6.0

    def __init__(
        self,
        *,
        board: str = "release-notes",
        feed_url: str = _FEED_URL,
        timeout: float = 15.0,
    ):
        self.board = board
        self.feed_url = feed_url
        self.timeout = float(timeout)
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "GoogleCloudReleaseNotesAdapter":
        self._client = httpx.AsyncClient(headers=_HEADERS, timeout=self.timeout, follow_redirects=True)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get_xml(self) -> str:
        client = self._client
        if client is None:
            async with httpx.AsyncClient(headers=_HEADERS, timeout=self.timeout, follow_redirects=True) as c:
                r = await c.get(self.feed_url)
        else:
            r = await client.get(self.feed_url)
        r.raise_for_status()
        return r.text

    @staticmethod
    def _text(node: Optional[Tag]) -> str:
        return node.get_text(" ", strip=True) if node else ""

    @staticmethod
    def _post_id(*, entry_id: str, product: str, kind: str, text: str) -> str:
        raw = f"{entry_id}|{product}|{kind}|{text}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]

    @staticmethod
    def _title(*, product: str, kind: str, text: str) -> str:
        lead = text.split(". ", 1)[0].strip() or text.strip()
        prefix = " - ".join(part for part in (product, kind) if part)
        title = f"{prefix}: {lead}" if prefix else lead
        return title[:180]

    def _parse_content(
        self,
        *,
        entry_id: str,
        entry_url: Optional[str],
        published_at: Optional[str],
        html: str,
        page_size: int,
    ) -> list[NoticePost]:
        soup = BeautifulSoup(html or "", "lxml")
        root = soup.body or soup
        posts: list[NoticePost] = []
        product = ""
        kind = ""
        section_nodes: list[Tag] = []

        def flush() -> None:
            nonlocal section_nodes
            if not product or not kind or not section_nodes:
                section_nodes = []
                return
            body = "".join(str(n) for n in section_nodes)
            text = " ".join(n.get_text(" ", strip=True) for n in section_nodes).strip()
            if not text:
                section_nodes = []
                return
            post_id = self._post_id(entry_id=entry_id, product=product, kind=kind, text=text)
            posts.append(
                NoticePost(
                    site=self.site,
                    board=self.board,
                    post_id=post_id,
                    title=self._title(product=product, kind=kind, text=text),
                    url=(f"{entry_url}-{post_id}" if entry_url else None),
                    published_at=published_at,
                    author=product,
                    category=kind,
                    summary=text[:1000],
                    content_html=body,
                    raw={
                        "source": "google_cloud_release_notes_atom",
                        "entry_id": entry_id,
                        "product": product,
                        "kind": kind,
                    },
                )
            )
            section_nodes = []

        for node in root.find_all(["h2", "h3", "p", "ul", "ol", "table"], recursive=False):
            if node.name == "h2":
                flush()
                product = self._text(node)
                kind = ""
                continue
            if node.name == "h3":
                flush()
                kind = self._text(node)
                continue
            if product and kind:
                section_nodes.append(node)
                if len(posts) >= page_size:
                    return posts
        flush()
        return posts[:page_size]

    def _parse_feed(self, xml: str, *, page_size: int = 30) -> list[NoticePost]:
        soup = BeautifulSoup(xml or "", "xml")
        posts: list[NoticePost] = []
        for entry in soup.find_all("entry"):
            entry_id = self._text(entry.find("id"))
            if not entry_id:
                continue
            updated = self._text(entry.find("updated")) or None
            link = entry.find("link", rel="alternate") or entry.find("link")
            entry_url = link.get("href") if isinstance(link, Tag) and link.has_attr("href") else None
            content = entry.find("content")
            html = content.get_text() if content else ""
            posts.extend(
                self._parse_content(
                    entry_id=entry_id,
                    entry_url=entry_url,
                    published_at=updated,
                    html=html,
                    page_size=max(0, page_size - len(posts)),
                )
            )
            if len(posts) >= page_size:
                break
        return posts

    async def fetch_list(self, *, page: int = 1, page_size: int = 10) -> list[NoticePost]:
        if page > 1:
            return []
        xml = await self._get_xml()
        posts = self._parse_feed(xml, page_size=page_size)
        await self.polite_sleep()
        return posts

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        return replace(post, content_html=post.content_html or post.summary)
