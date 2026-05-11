"""사이트 단위 병렬 수집 오케스트레이터.

- 한 어댑터 = 한 task. asyncio.gather 로 동시 실행.
- 같은 host 어댑터가 둘 이상이면 host 단위 Semaphore(1) 로 자동 직렬화 →
  Crawl-Delay 가 깨지지 않음.
- 한 사이트 실패가 다른 사이트를 죽이지 않도록 return_exceptions=True.
- 어댑터 안의 article 순회는 직렬 + 어댑터 자체 polite_sleep.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

from .base import BaseAdapter, NoticePost


@dataclass
class SiteResult:
    site: str
    posts: list[NoticePost]
    error: Optional[BaseException] = None

    @property
    def ok(self) -> bool:
        return self.error is None


async def collect_parallel(
    adapters: list[BaseAdapter],
    *,
    fetch_articles: bool = True,
    article_limit_per_site: Optional[int] = None,
    list_page: int = 1,
    list_page_size: int = 30,
) -> list[SiteResult]:
    """모든 어댑터를 병렬로 돌려 NoticePost 리스트를 사이트별로 반환.

    Args:
        fetch_articles: True 면 본문(content_html)까지 fetch. False 면 목록만.
        article_limit_per_site: 본문 fetch 상한 (None = 전체).
        list_page, list_page_size: fetch_list 인자.
    """
    if not adapters:
        return []

    host_locks: dict[str, asyncio.Semaphore] = {}
    for a in adapters:
        host_locks.setdefault(a.host or a.site, asyncio.Semaphore(1))

    async def run_one(a: BaseAdapter) -> list[NoticePost]:
        lock_key = a.host or a.site
        async with host_locks[lock_key]:
            async with a:
                posts = await a.fetch_list(page=list_page, page_size=list_page_size)
                if not fetch_articles:
                    return posts
                limit = article_limit_per_site if article_limit_per_site is not None else len(posts)
                fetched: list[NoticePost] = []
                for i, p in enumerate(posts[:limit]):
                    if i > 0:
                        await a.polite_sleep()
                    fetched.append(await a.fetch_article(p))
                # 본문을 받지 않은 나머지 글도 그대로 포함
                fetched.extend(posts[limit:])
                return fetched

    tasks = [(a.site, asyncio.create_task(run_one(a))) for a in adapters]
    raw_results = await asyncio.gather(*(t for _, t in tasks), return_exceptions=True)

    out: list[SiteResult] = []
    for (site, _), res in zip(tasks, raw_results):
        if isinstance(res, BaseException):
            out.append(SiteResult(site=site, posts=[], error=res))
        else:
            out.append(SiteResult(site=site, posts=res))
    return out
