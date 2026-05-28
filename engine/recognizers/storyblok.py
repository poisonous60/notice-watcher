"""Storyblok `/story-data/all-stories.json` config builder."""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlsplit

NAME = "storyblok"


def _origin(url: str) -> Optional[str]:
    try:
        parts = urlsplit(url)
    except (TypeError, ValueError):
        return None
    host = (parts.netloc or "").strip().lower()
    if not host or "." not in host:
        return None
    return f"{parts.scheme or 'https'}://{host}"


def _board_from_url(url: str) -> str:
    try:
        path = (urlsplit(url).path or "").strip("/")
    except (TypeError, ValueError):
        path = ""
    first = path.split("/", 1)[0].strip()
    if first and first != "story-data":
        return first
    return "news"


def build_config(base_url: str, *, story_data_url: Optional[str] = None, board: Optional[str] = None) -> Optional[dict]:
    origin = _origin(base_url or story_data_url or "")
    if not origin:
        return None
    host = urlsplit(origin).netloc.lower()
    board_id = (board or _board_from_url(base_url) or "news").strip("/") or "news"
    api = (story_data_url or f"{origin}/story-data/all-stories.json").strip()
    return {
        "version": 1,
        "site": host,
        "board": board_id,
        "strategy": "handwritten",
        "adapter": "StoryblokAllStoriesAdapter",
        "kwargs": {
            "base_url": origin,
            "story_data_url": api,
            "board": board_id,
        },
        "_slug_board": f"{host}_{board_id}",
        "_source_url": api,
        "_note": "Storyblok all-stories JSON — card list HTML may use Tailwind utility classes; body comes from Storyblok rich-text JSON.",
    }


def _build(m: "re.Match", url: str) -> Optional[dict]:
    return build_config(url, story_data_url=url)


PATTERNS = [
    (re.compile(r"^https?://[^/?#]+/story-data/all-stories\.json(?:[?#].*)?$", re.I), _build),
]
