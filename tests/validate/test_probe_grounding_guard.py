"""Probe-evidence grounding guard for generated validator candidates.

The guard must reject expensive, unsupported Playwright selectors before
network/browser work, while still allowing selectors synthesized from actual
probe HTML rather than verbatim candidate strings.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from engine.base_compat import BaseAdapter, NoticePost
from generate.validate import ValidationReport, _add_probe_grounding_checks, validate_built_config


class _GroundingFakeAdapter(BaseAdapter):
    fetch_list_called = 0

    def __init__(self):
        self.site = "example.com"
        self.board = "news"
        self.host = self.site

    async def __aenter__(self):  # noqa: D401
        return self

    async def __aexit__(self, *exc):  # noqa: D401
        return None

    async def fetch_list(self, *, page: int = 1, page_size: int = 30):
        type(self).fetch_list_called += 1
        return [NoticePost(
            site=self.site,
            board=self.board,
            post_id="p1",
            title="Title",
            url="https://example.com/news/p1",
        )]

    async def fetch_article(self, post: NoticePost) -> NoticePost:
        return NoticePost(
            site=post.site,
            board=post.board,
            post_id=post.post_id,
            title=post.title,
            url=post.url,
            content_html="<main>" + ("body " * 40) + "</main>",
        )


def _html_cfg(*, strategy: str = "playwright_html", row: str = "article.card", wait: str | None = None) -> dict:
    cfg: dict = {
        "version": 1,
        "site": "example.com",
        "board": "news",
        "strategy": strategy,
        "list": {
            "url_template": "https://example.com/news/",
            "pagination": {"kind": "none"},
            "row_selector": row,
            "fields": {
                "post_id": [{"from": "css", "selector": "a", "attr": "href"}],
                "title": [{"from": "css", "selector": "a", "text": True}],
                "url": [{"from": "css", "selector": "a", "attr": "href"}],
            },
        },
        "article": {
            "fetch_kind": "html",
            "content": [{"from": "css", "selector": "main.article-body", "html": True}],
        },
    }
    if wait:
        cfg["list"]["wait_selector"] = wait
        cfg["article"]["wait_selector"] = "main.article-body"
    return cfg


def _handwritten_cfg(*, row: str = "article.card") -> dict:
    return {
        "version": 1,
        "site": "example.com",
        "board": "news",
        "strategy": "handwritten",
        "adapter": "_GroundingFakeAdapter",
        "kwargs": {},
        "list": {"url_template": "https://example.com/news/", "row_selector": row, "fields": {}},
        "article": {"fetch_kind": "html"},
    }


def _digest(*, compressed: bool = False, api_candidates: list[dict] | None = None) -> dict:
    return {
        "list_html": {
            "source": "list.html",
            "truncated": False,
            "prompt_compressed": compressed,
            "html": """
                <body>
                  <article class="card"><a href="/news/p1">Title</a></article>
                </body>
            """,
        },
        "article_sample": {
            "source": "article.html",
            "truncated": False,
            "prompt_compressed": compressed,
            "html": "<body><main class='article-body'>Body</main></body>",
            "api_candidates": api_candidates,
        },
    }


def _run(coro):
    return asyncio.run(coro)


def run() -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []

    # 1) Unsupported Playwright wait selector fails before browser/network work.
    rep = _run(validate_built_config(
        _html_cfg(wait="section.made-up"),
        digest=_digest(),
        fetch_articles=0,
    ))
    cases.append((
        "playwright_wait_selector_zero_match_fast_fails",
        any(c.name == "probe_grounding_list_wait_selector" and c.hard and not c.ok for c in rep.checks),
        f"checks={[(c.name, c.ok, c.detail) for c in rep.checks]}",
    ))

    # 2) Synthesized selectors are fine when they match probe HTML.
    import adapters as _ad
    _GroundingFakeAdapter.fetch_list_called = 0
    _ad._GroundingFakeAdapter = _GroundingFakeAdapter  # type: ignore[attr-defined]
    try:
        rep = _run(validate_built_config(_handwritten_cfg(), digest=_digest(), fetch_articles=1))
    finally:
        try:
            delattr(_ad, "_GroundingFakeAdapter")
        except AttributeError:
            pass
    cases.append((
        "matching_digest_does_not_block_handwritten_path",
        rep.ok and _GroundingFakeAdapter.fetch_list_called == 1,
        f"ok={rep.ok} hard={[(c.name, c.detail) for c in rep.hard_failures()]} calls={_GroundingFakeAdapter.fetch_list_called}",
    ))

    # 3) Compressed digest is not hard negative evidence.
    import adapters as _ad2
    _GroundingFakeAdapter.fetch_list_called = 0
    _ad2._GroundingFakeAdapter = _GroundingFakeAdapter  # type: ignore[attr-defined]
    try:
        rep = _run(validate_built_config(
            _handwritten_cfg(row="section.made-up"),
            digest=_digest(compressed=True),
            fetch_articles=0,
        ))
    finally:
        try:
            delattr(_ad2, "_GroundingFakeAdapter")
        except AttributeError:
            pass
    cases.append((
        "compressed_digest_fails_open",
        not any(c.name.startswith("probe_grounding_") for c in rep.checks),
        f"checks={[(c.name, c.ok) for c in rep.checks]} error={rep.error}",
    ))

    # 4) Static fallback HTML is not hard negative evidence for Playwright.
    d = _digest()
    d["list_html"]["source"] = "s1.http.html"
    direct = ValidationReport()
    _add_probe_grounding_checks(direct, _html_cfg(wait="section.made-up"), d)
    cases.append((
        "playwright_static_fallback_digest_fails_open",
        not any(c.name.startswith("probe_grounding_") for c in direct.checks),
        f"checks={[(c.name, c.ok, c.detail) for c in direct.checks]}",
    ))

    # 5) JSON article API must be grounded when probe captured useful body API candidates.
    cfg = _html_cfg(strategy="httpx_html")
    cfg["article"] = {
        "fetch_kind": "json",
        "url_template": "https://example.com/api/other/{post_id}.json",
        "content": [{"from": "json", "path": ["body"]}],
    }
    rep = _run(validate_built_config(
        cfg,
        digest=_digest(api_candidates=[{
            "url": "https://example.com/api/news/p1.json",
            "url_id_match": True,
            "body_looks_html": True,
            "body_field_path": ["body"],
        }]),
        fetch_articles=0,
    ))
    cases.append((
        "ungrounded_article_json_api_fast_fails",
        any(c.name == "probe_grounding_article_json_api" and c.hard and not c.ok for c in rep.checks),
        f"checks={[(c.name, c.ok, c.detail) for c in rep.checks]}",
    ))

    return cases


if __name__ == "__main__":
    fail = 0
    for name, ok, msg in run():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  ({msg})")
        fail += 0 if ok else 1
    raise SystemExit(0 if fail == 0 else 1)
