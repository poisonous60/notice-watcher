from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import replace
from typing import Optional
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Tag

from .base import BaseAdapter, NoticePost


_ROOT_SITEMAP = "https://developer.salesforce.com/docs/ssg-sitemap.xml"
_BASE_URL = "https://developer.salesforce.com/"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "application/xml,text/xml,text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://developer.salesforce.com/",
}
_RELEASE_URL_RE = re.compile(r"(?:release-notes|whatsnew|whats-new|whatswasnew)", re.I)


class SalesforceDocsReleaseNotesAdapter(BaseAdapter):
    site = "developer.salesforce.com"
    host = "developer.salesforce.com"
    polite_sleep_min = 5.0
    polite_sleep_max = 8.0

    def __init__(
        self,
        *,
        board: str = "docs",
        root_sitemap: str = _ROOT_SITEMAP,
        timeout: float = 20.0,
    ):
        self.board = board
        self.root_sitemap = root_sitemap
        self.timeout = float(timeout)

    @staticmethod
    def _request_text(url: str, *, timeout: float) -> str:
        try:
            from curl_cffi import requests
        except ImportError as ex:  # pragma: no cover - dependency guard for deployments
            raise RuntimeError("SalesforceDocsReleaseNotesAdapter requires curl_cffi") from ex

        r = requests.get(
            url,
            headers=_HEADERS,
            impersonate="chrome",
            timeout=timeout,
            allow_redirects=True,
        )
        r.raise_for_status()
        return r.text

    async def _get_text(self, url: str) -> str:
        return await asyncio.to_thread(self._request_text, url, timeout=self.timeout)

    @staticmethod
    def _locs(xml: str) -> list[str]:
        soup = BeautifulSoup(xml or "", "xml")
        return [loc.get_text(strip=True) for loc in soup.find_all("loc") if loc.get_text(strip=True)]

    async def _release_urls(self) -> list[str]:
        root_xml = await self._get_text(self.root_sitemap)
        first_level = self._locs(root_xml)
        release_urls: list[str] = []
        seen: set[str] = set()

        for index_url in first_level:
            index_xml = await self._get_text(index_url)
            for leaf_url in self._locs(index_xml):
                leaf_xml = await self._get_text(leaf_url)
                for url in self._locs(leaf_xml):
                    if not _RELEASE_URL_RE.search(url):
                        continue
                    if url in seen:
                        continue
                    seen.add(url)
                    release_urls.append(url)
        return release_urls

    @staticmethod
    def _post_id(url: str) -> str:
        path = urlsplit(url).path.strip("/")
        if path:
            return path.replace("/", "__").replace(".html", "")
        return hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]

    @staticmethod
    def _title_from_url(url: str) -> str:
        path = urlsplit(url).path.strip("/")
        parts = [p for p in path.split("/") if p and p not in {"docs", "guide", "references"}]
        product = ""
        if "platform" in parts:
            i = parts.index("platform")
            product = parts[i + 1] if i + 1 < len(parts) else ""
        elif len(parts) >= 2:
            product = parts[1]
        page = parts[-1].replace(".html", "") if parts else "release-notes"
        words = " ".join((product or page).replace("-", " ").split())
        suffix = "What Was New" if "whatswasnew" in page.lower() else "Release Notes"
        if words and suffix.lower() not in words.lower():
            return f"{words.title()} {suffix}"
        return words.title() or "Salesforce Developers Release Notes"

    @staticmethod
    def _main_content(soup: BeautifulSoup) -> Optional[Tag]:
        for selector in ("main", "article", "#content-container", ".content", "[role='main']"):
            node = soup.select_one(selector)
            if isinstance(node, Tag):
                return node
        body = soup.body
        return body if isinstance(body, Tag) else None

    def _parse_article(self, html: str, *, post: NoticePost) -> NoticePost:
        soup = BeautifulSoup(html or "", "lxml")
        title_node = soup.find("h1") or soup.find("title")
        title = title_node.get_text(" ", strip=True) if title_node else post.title
        meta_desc = soup.find("meta", attrs={"name": "description"})
        summary = None
        if isinstance(meta_desc, Tag):
            summary = meta_desc.get("content")
        content_node = self._main_content(soup)
        content_html = str(content_node) if content_node else (summary or title)
        return replace(
            post,
            title=title or post.title,
            summary=str(summary or post.summary or "").strip() or None,
            content_html=content_html,
            raw={**post.raw, "source": "salesforce_docs_sitemap"},
        )

    async def fetch_list(self, *, page: int = 1, page_size: int = 10) -> list[NoticePost]:
        if page > 1:
            return []
        urls = await self._release_urls()
        posts = [
            NoticePost(
                site=self.site,
                board=self.board,
                post_id=self._post_id(url),
                title=self._title_from_url(url),
                url=url,
                raw={"source": "salesforce_docs_sitemap"},
            )
            for url in urls[:page_size]
        ]
        await self.polite_sleep()
        return posts

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        if not post.url:
            return replace(post, content_html=post.summary or post.title)
        html = await self._get_text(post.url)
        parsed = self._parse_article(html, post=post)
        await self.polite_sleep()
        return parsed
