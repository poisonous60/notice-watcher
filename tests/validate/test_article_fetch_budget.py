"""Validator article fetch budget should stay bounded for agentic candidate checks.

`fetch_articles=1` needs one real body verdict plus a small spare for skip-status
or access-restricted first posts. It should not burn five article navigations on
bad generated selectors.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from engine.base_compat import BaseAdapter, NoticePost
from generate.validate import validate_built_config


class _AlwaysFailArticleAdapter(BaseAdapter):
    def __init__(self, *, n_posts: int = 6):
        self.site = "fake.example.com"
        self.board = "budget"
        self.host = self.site
        self.article_calls: list[str] = []
        self._posts = [
            NoticePost(
                site=self.site,
                board=self.board,
                post_id=f"P{i}",
                title=f"Title {i}",
                url=f"https://fake.example.com/p/{i}",
            )
            for i in range(n_posts)
        ]

    async def __aenter__(self):  # noqa: D401
        return self

    async def __aexit__(self, *exc):  # noqa: D401
        return None

    async def fetch_list(self, *, page: int = 1, page_size: int = 30):
        return self._posts

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        self.article_calls.append(str(post.post_id))
        raise RuntimeError("article selector never resolves")


def _cfg() -> dict:
    return {
        "version": 1,
        "site": "fake.example.com",
        "board": "budget",
        "strategy": "handwritten",
        "adapter": "_BudgetAdapter",
        "kwargs": {},
        "list": {"url_template": "https://fake.example.com/list", "fields": {}},
        "article": {"url_template": "https://fake.example.com/p/{post_id}", "fetch_kind": "html"},
    }


def run() -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []
    import adapters as _ad

    adapter = _AlwaysFailArticleAdapter()
    _ad._BudgetAdapter = lambda **kw: adapter  # type: ignore[attr-defined]
    try:
        rep = asyncio.run(validate_built_config(_cfg(), fetch_articles=1))
    finally:
        try:
            delattr(_ad, "_BudgetAdapter")
        except AttributeError:
            pass

    cases.append((
        "fetch_articles_1_uses_one_spare_only",
        adapter.article_calls == ["P0", "P1"],
        f"article_calls={adapter.article_calls!r}",
    ))
    cases.append((
        "no_body_still_hard_fails",
        any(c.name == "article_body_len" and c.hard and not c.ok for c in rep.hard_failures()),
        f"hard_failures={[(c.name, c.detail) for c in rep.hard_failures()]}",
    ))
    return cases


if __name__ == "__main__":
    fail = 0
    for name, ok, msg in run():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  ({msg})")
        fail += 0 if ok else 1
    raise SystemExit(0 if fail == 0 else 1)
