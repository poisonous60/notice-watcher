from __future__ import annotations

import asyncio
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class NoticePost:
    site: str
    board: str
    post_id: str
    title: str
    url: Optional[str]
    published_at: Optional[str] = None    # ISO8601
    author: Optional[str] = None
    category: Optional[str] = None
    summary: Optional[str] = None
    content_html: Optional[str] = None
    cover_image: Optional[str] = None
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class BaseAdapter(ABC):
    site: str = "unknown"
    board: str = "default"
    # 호스트 단위 lock 키. collect_parallel 가 같은 host 어댑터를 직렬화한다.
    host: str = ""
    # 어댑터별 호출 간격. dcinside 등은 robots.txt Crawl-Delay 에 맞춰 override.
    polite_sleep_min: float = 2.0
    polite_sleep_max: float = 5.0

    @abstractmethod
    async def fetch_list(self, *, page: int = 1, page_size: int = 10) -> list[NoticePost]:
        """게시판 1페이지의 글 목록을 NoticePost로 반환. 본문은 비워둠."""

    @abstractmethod
    async def fetch_article(self, post: NoticePost) -> NoticePost:
        """주어진 NoticePost에 본문(content_html)을 채워 새 객체 반환."""

    async def __aenter__(self) -> "BaseAdapter":
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def polite_sleep(self) -> None:
        base = random.uniform(self.polite_sleep_min, self.polite_sleep_max)
        jitter = base * random.uniform(-0.3, 0.3)
        await asyncio.sleep(max(0.5, base + jitter))
