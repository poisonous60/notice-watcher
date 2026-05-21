from __future__ import annotations

import asyncio
import re
from dataclasses import replace
from typing import Optional
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from curl_cffi import requests

from .base import BaseAdapter, NoticePost


_BASE = "https://main--cc--adobecom.aem.live"
_DEFAULT_URL = "https://www.adobe.com/creativecloud/features.html"
_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": _DEFAULT_URL,
}
_CARD_INDEX = "/cc-shared/fragments/creativecloud/features/editorial-cards-new-features"
_CARD_RE = re.compile(r"/cc-shared/fragments/creativecloud/features/editorial-card-new-feature-([a-z0-9-]+)")


class AdobeCreativeCloudFeaturesAdapter(BaseAdapter):
    site = "Adobe"
    host = "www.adobe.com"
    polite_sleep_min = 5.0
    polite_sleep_max = 8.0

    def __init__(
        self,
        *,
        board: str = "products",
        url: str = _DEFAULT_URL,
        timeout: float = 30.0,
    ):
        self.board = board
        self.url = url
        self.timeout = float(timeout)

    def _get_text_sync(self, url: str) -> str:
        r = requests.get(url, impersonate="chrome", headers=_HEADERS, timeout=self.timeout)
        r.raise_for_status()
        return r.text

    async def _get_text(self, url: str) -> str:
        return await asyncio.to_thread(self._get_text_sync, url)

    @staticmethod
    def _clean(text: object) -> str:
        value = " ".join(str(text or "").split())
        value = re.sub(r"\{\{([^{}|]+)\}\}", r"\1", value)
        value = value.replace("|", " ")
        return " ".join(value.split()).strip()

    @classmethod
    def _absolute_aem(cls, href: str) -> str:
        if href.startswith("http"):
            parts = urlsplit(href)
            return _BASE + parts.path
        return urljoin(_BASE, href)

    @classmethod
    def _card_paths(cls, html: str) -> list[tuple[str, str]]:
        soup = BeautifulSoup(html, "lxml")
        seen: set[str] = set()
        out: list[tuple[str, str]] = []
        for a in soup.select("a[href]"):
            href = str(a.get("href") or "")
            m = _CARD_RE.search(href)
            if not m:
                continue
            slug = m.group(1)
            if slug in seen:
                continue
            seen.add(slug)
            out.append((slug, cls._absolute_aem(href.split("#", 1)[0])))
        return out

    @classmethod
    def _post_from_card(cls, slug: str, url: str, html: str) -> Optional[NoticePost]:
        soup = BeautifulSoup(html, "lxml")
        title_node = soup.select_one("h3")
        title = cls._clean(title_node.get_text(" ", strip=True) if title_node else "")
        if not title:
            return None
        icon_text = cls._clean((soup.select_one("p") or "").get_text(" ", strip=True) if soup.select_one("p") else "")
        app = icon_text.rsplit(" ", 1)[-1] if icon_text else slug.replace("-", " ").title()
        feature_link = None
        for a in soup.select("a[href]"):
            text = cls._clean(a.get_text(" ", strip=True))
            href = str(a.get("href") or "")
            if "New features" in text and "modals/feature-" in href:
                feature_link = cls._absolute_aem(href.split("#", 1)[0])
                break
        return NoticePost(
            site=cls.site,
            board="products",
            post_id=slug,
            title=title,
            url=feature_link or url,
            author="Adobe",
            category=app,
            summary=title,
            raw={"source": "adobe_creative_cloud_features", "card_url": url},
        )

    async def fetch_list(self, *, page: int = 1, page_size: int = 10) -> list[NoticePost]:
        if page > 1:
            return []
        # The old /products/new-creative-cloud-features.html URL now 404s; the
        # current public page links to the same AEM feature-card fragments.
        await self._get_text(self.url)
        index_html = await self._get_text(_BASE + _CARD_INDEX)
        posts: list[NoticePost] = []
        for slug, card_url in self._card_paths(index_html):
            card_html = await self._get_text(card_url)
            post = self._post_from_card(slug, card_url, card_html)
            if post is not None:
                posts.append(replace(post, board=self.board))
            if len(posts) >= page_size:
                break
        await self.polite_sleep()
        return posts

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        if not post.url:
            return post
        html = await self._get_text(post.url)
        soup = BeautifulSoup(html, "lxml")
        content = soup.select_one("main") or soup.body
        content_html = str(content) if content is not None else None
        summary_node = soup.select_one("h3")
        summary = self._clean(summary_node.get_text(" ", strip=True) if summary_node else post.summary)
        await self.polite_sleep()
        return replace(post, summary=summary or post.summary, content_html=content_html, raw={**post.raw, "article_url": post.url})
