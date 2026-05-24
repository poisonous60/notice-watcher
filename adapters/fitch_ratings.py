"""Fitch Ratings research adapter."""
from __future__ import annotations

from dataclasses import replace
from html import escape
from typing import Optional

import httpx

from .base import BaseAdapter, NoticePost


_API_URL = "https://api.fitchratings.com/"
_BASE_URL = "https://www.fitchratings.com/"
_QUERY = """
query Insights(
  $analyst: String
  $country: String
  $entity: String
  $language: String
  $contentType: String
  $region: String
  $sector: String
  $topic: String
  $insightsTaggedOnlySector: Boolean
  $reportType: String
) {
  getInsights(
    analyst: $analyst
    country: $country
    entity: $entity
    language: $language
    contentType: $contentType
    region: $region
    sector: $sector
    topic: $topic
    insightsTaggedOnlySector: $insightsTaggedOnlySector
    reportType: $reportType
  ) {
    rows {
      publishedDate
      docType
      reportType
      slug
      title
      marketing {
        contentAccessType {
          name
          slug
        }
        language {
          name
          slug
        }
      }
    }
  }
}
"""
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://www.fitchratings.com",
    "Referer": "https://www.fitchratings.com/research",
}


class FitchRatingsResearchAdapter(BaseAdapter):
    site = "fitchratings.com"
    host = "api.fitchratings.com"
    board = "research"
    polite_sleep_min = 5.0
    polite_sleep_max = 8.0

    def __init__(self, *, timeout: float = 20.0):
        self.timeout = float(timeout)
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "FitchRatingsResearchAdapter":
        self._client = httpx.AsyncClient(headers=_HEADERS, timeout=self.timeout, follow_redirects=True)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _post_json(self, body: dict) -> dict:
        client = self._client
        if client is None:
            async with httpx.AsyncClient(headers=_HEADERS, timeout=self.timeout, follow_redirects=True) as c:
                r = await c.post(_API_URL, json=body)
        else:
            r = await client.post(_API_URL, json=body)
        r.raise_for_status()
        payload = r.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Fitch Ratings API payload is not an object")
        if payload.get("errors"):
            raise RuntimeError(f"Fitch Ratings API errors: {payload['errors']}")
        return payload

    @staticmethod
    def _post_from_row(row: dict) -> Optional[NoticePost]:
        title = str(row.get("title") or "").strip()
        slug = str(row.get("slug") or "").strip().strip("/")
        if not title or not slug:
            return None
        marketing = row.get("marketing") if isinstance(row.get("marketing"), dict) else {}
        language = marketing.get("language") if isinstance(marketing.get("language"), dict) else {}
        access = marketing.get("contentAccessType") if isinstance(marketing.get("contentAccessType"), dict) else {}
        category = str(row.get("reportType") or row.get("docType") or "").strip() or None
        lang = str(language.get("name") or "").strip()
        if lang:
            category = f"{category} / {lang}" if category else lang
        return NoticePost(
            site=FitchRatingsResearchAdapter.site,
            board=FitchRatingsResearchAdapter.board,
            post_id=slug,
            title=title,
            url=_BASE_URL + "research/" + slug,
            published_at=str(row.get("publishedDate") or "").strip() or None,
            author="Fitch Ratings",
            category=category,
            summary=str(access.get("name") or "").strip() or None,
            raw={"_strategy": "fitch_ratings_research", "_item": row},
        )

    async def fetch_list(self, *, page: int = 1, page_size: int = 10) -> list[NoticePost]:
        if page > 1:
            return []
        payload = await self._post_json(
            {
                "operationName": "Insights",
                "variables": {},
                "query": _QUERY,
            }
        )
        rows = (((payload.get("data") or {}).get("getInsights") or {}).get("rows") or [])
        posts: list[NoticePost] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            post = self._post_from_row(row)
            if post is None:
                continue
            posts.append(post)
            if len(posts) >= page_size:
                break
        return posts

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        parts = [
            f"<p>{escape(post.title)}</p>",
            f"<p>{escape(post.category or 'Research')}</p>",
        ]
        if post.published_at:
            parts.append(f"<p>{escape(post.published_at)}</p>")
        if post.url:
            parts.append(f'<p><a href="{escape(post.url)}">{escape(post.url)}</a></p>')
        return replace(post, content_html="\n".join(parts), raw={**post.raw, "fetched_url": post.url})
