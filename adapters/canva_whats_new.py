from __future__ import annotations

import asyncio
import re
from dataclasses import replace
from typing import Optional
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
from curl_cffi import requests

from .base import BaseAdapter, NoticePost


_SITEMAP_URL = "https://www.canva.com/landing_page_sitemap_1.xml"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.canva.com/newsroom/",
}


class CanvaWhatsNewAdapter(BaseAdapter):
    site = "www.canva.com"
    host = "www.canva.com"
    polite_sleep_min = 5.0
    polite_sleep_max = 8.0

    def __init__(
        self,
        *,
        board: str = "whats-new",
        sitemap_url: str = _SITEMAP_URL,
        timeout: float = 20.0,
    ):
        self.board = board
        self.sitemap_url = sitemap_url
        self.timeout = float(timeout)
        self._session: Optional[requests.Session] = None

    async def __aenter__(self) -> "CanvaWhatsNewAdapter":
        self._session = requests.Session(impersonate="chrome")
        return self

    async def __aexit__(self, *exc) -> None:
        self._session = None

    def _get_text_sync(self, url: str) -> str:
        session = self._session or requests.Session(impersonate="chrome")
        r = session.get(url, headers=_HEADERS, timeout=self.timeout)
        r.raise_for_status()
        return r.text

    async def _get_text(self, url: str) -> str:
        return await asyncio.to_thread(self._get_text_sync, url)

    @staticmethod
    def _is_whats_new_url(url: str) -> bool:
        parts = urlsplit(url)
        path = parts.path
        if parts.netloc != "www.canva.com" or not path.startswith("/newsroom/news/"):
            return False
        return "whats-new" in path.lower()

    @staticmethod
    def _post_id(url: str) -> str:
        slug = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
        return re.sub(r"[^A-Za-z0-9._-]+", "-", slug).strip("-").lower()

    @staticmethod
    def _title_from_url(url: str) -> str:
        slug = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
        title = re.sub(r"[-_]+", " ", slug).strip()
        return title[:1].upper() + title[1:] if title else url

    def _parse_sitemap(self, xml: str, *, page_size: int) -> list[NoticePost]:
        root = ET.fromstring(xml)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        posts: list[NoticePost] = []
        seen: set[str] = set()
        for url_node in root.findall("sm:url", ns):
            loc = url_node.findtext("sm:loc", default="", namespaces=ns).strip()
            if not loc or loc in seen or not self._is_whats_new_url(loc):
                continue
            seen.add(loc)
            posts.append(
                NoticePost(
                    site=self.site,
                    board=self.board,
                    post_id=self._post_id(loc),
                    title=self._title_from_url(loc),
                    url=loc,
                    raw={"source": "canva_landing_page_sitemap"},
                )
            )
            if len(posts) >= page_size:
                break
        return posts

    @staticmethod
    def _clean_article_html(html: str) -> tuple[str, str]:
        soup = BeautifulSoup(html or "", "lxml")
        for node in soup(["script", "style", "svg", "noscript", "template", "iframe", "nav", "footer"]):
            node.decompose()
        title = ""
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(" ", strip=True)
        content = soup.find("main") or soup.find("article") or soup.body or soup
        return title, str(content)

    async def fetch_list(self, *, page: int = 1, page_size: int = 10) -> list[NoticePost]:
        if page > 1:
            return []
        xml = await self._get_text(self.sitemap_url)
        posts = self._parse_sitemap(xml, page_size=page_size)
        await self.polite_sleep()
        return posts

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        if not post.url:
            return post
        html = await self._get_text(post.url)
        title, content_html = self._clean_article_html(html)
        return replace(
            post,
            title=title or post.title,
            content_html=content_html,
        )
