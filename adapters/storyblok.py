"""Storyblok all-stories JSON adapter.

Some Nuxt/Storyblok sites render card lists in static HTML but keep article
body content in Storyblok rich-text JSON. This adapter reads the stable
`/story-data/all-stories.json` payload and filters one board prefix.
"""
from __future__ import annotations

import html
from typing import Any, Optional
from urllib.parse import urljoin, urlsplit

import httpx

from .base import BaseAdapter, NoticePost


def _text_from_richtext(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        return str(node.get("text") or "")
    return "".join(_text_from_richtext(child) for child in (node.get("content") or []))


def _richtext_to_html(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    typ = node.get("type")
    if typ == "text":
        text = html.escape(str(node.get("text") or ""))
        marks = node.get("marks") or []
        for mark in marks:
            if not isinstance(mark, dict):
                continue
            name = mark.get("type")
            if name == "bold":
                text = f"<strong>{text}</strong>"
            elif name == "italic":
                text = f"<em>{text}</em>"
            elif name == "link":
                href = html.escape(str((mark.get("attrs") or {}).get("href") or ""), quote=True)
                if href:
                    text = f'<a href="{href}">{text}</a>'
        return text

    children = "".join(_richtext_to_html(child) for child in (node.get("content") or []))
    if typ == "doc":
        return children
    if typ == "paragraph":
        return f"<p>{children}</p>" if children.strip() else ""
    if typ == "heading":
        level = int((node.get("attrs") or {}).get("level") or 2)
        level = min(max(level, 1), 6)
        return f"<h{level}>{children}</h{level}>"
    if typ == "bullet_list":
        return f"<ul>{children}</ul>"
    if typ == "ordered_list":
        return f"<ol>{children}</ol>"
    if typ == "list_item":
        return f"<li>{children}</li>"
    if typ == "hard_break":
        return "<br>"
    return children


class StoryblokAllStoriesAdapter(BaseAdapter):
    polite_sleep_min = 2.0
    polite_sleep_max = 4.0

    def __init__(self, *, base_url: str, story_data_url: str, board: str = "news", timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.story_data_url = story_data_url
        self.board = (board or "news").strip("/").split("/", 1)[0] or "news"
        parts = urlsplit(self.base_url)
        self.site = (parts.netloc or "storyblok").lower()
        self.host = self.site
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._stories_cache: Optional[list[dict]] = None

    async def __aenter__(self) -> "StoryblokAllStoriesAdapter":
        self._client = httpx.AsyncClient(timeout=self._timeout, follow_redirects=True)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _load_stories(self) -> list[dict]:
        if self._stories_cache is not None:
            return self._stories_cache
        async def _do(client: httpx.AsyncClient) -> list[dict]:
            r = await client.get(self.story_data_url)
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else []
        if self._client is not None:
            stories = await _do(self._client)
        else:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
                stories = await _do(client)
        self._stories_cache = stories
        return stories

    def _story_url(self, full_slug: str) -> str:
        return urljoin(self.base_url + "/", full_slug.strip("/"))

    def _summary(self, content: dict) -> Optional[str]:
        sub = content.get("subHeading")
        if isinstance(sub, str) and sub.strip():
            return sub.strip()
        intro = _text_from_richtext(content.get("articleIntro"))
        return intro.strip()[:500] if intro.strip() else None

    def _story_to_post(self, story: dict) -> Optional[NoticePost]:
        if not isinstance(story, dict):
            return None
        full_slug = str(story.get("full_slug") or "")
        if not full_slug.startswith(f"{self.board}/"):
            return None
        content = story.get("content") or {}
        if not isinstance(content, dict) or content.get("component") != "newsArticle":
            return None
        slug = str(story.get("slug") or full_slug.rsplit("/", 1)[-1]).strip()
        title = str(story.get("name") or "").strip()
        if not slug or not title:
            return None
        image = content.get("featuredImage") if isinstance(content.get("featuredImage"), dict) else {}
        cover = image.get("filename") if isinstance(image, dict) else None
        return NoticePost(
            site=self.site,
            board=self.board,
            post_id=slug,
            title=title,
            url=self._story_url(full_slug),
            published_at=story.get("published_at") or story.get("first_published_at") or story.get("created_at"),
            summary=self._summary(content),
            cover_image=urljoin(self.base_url + "/", cover.lstrip("/")) if isinstance(cover, str) and cover else None,
            raw={"_strategy": "storyblok_all_stories", "_story": story},
        )

    async def fetch_list(self, *, page: int = 1, page_size: int = 10) -> list[NoticePost]:
        stories = await self._load_stories()
        posts = [post for story in stories if (post := self._story_to_post(story)) is not None]
        posts.sort(key=lambda p: p.published_at or "", reverse=True)
        start = max(page - 1, 0) * page_size
        return posts[start:start + page_size]

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        story = (post.raw or {}).get("_story") or {}
        content = story.get("content") if isinstance(story, dict) else {}
        body = _richtext_to_html((content or {}).get("articleContent")) if isinstance(content, dict) else ""
        return NoticePost(
            site=post.site,
            board=post.board,
            post_id=post.post_id,
            title=post.title,
            url=post.url,
            published_at=post.published_at,
            author=post.author,
            category=post.category,
            summary=post.summary,
            content_html=body,
            cover_image=post.cover_image,
            raw=post.raw,
        )
