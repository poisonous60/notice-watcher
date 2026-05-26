"""httpx + bs4 (정적 HTML 게시판) strategy.

adapters/dcinside.py, adapters/skku_cse.py 를 일반화한 것.
파싱(HTML→NoticePost)은 `parse_list_html` / `parse_article_html` 로 분리 — playwright_html strategy 가 재사용.
ConfigAdapter 가 호출: open_session / close_session / fetch_list / fetch_article.
"""
from __future__ import annotations

from typing import Optional

import httpx

from .._http import build_async_client, get_with_tls_fallback
from ..base_compat import NoticePost
from ..extract_helpers import extract_field, extract_row, parse_html, parse_html_or_xml
from ..tracing import current_trace
from ._common import apply_proxy, build_list_url, render_template


# ---------- 세션 ----------

async def open_session(adapter) -> None:
    cfg = adapter.cfg
    adapter._client = build_async_client(cfg)


async def close_session(adapter) -> None:
    client = getattr(adapter, "_client", None)
    if client is not None:
        await client.aclose()
        adapter._client = None


async def _get(adapter, url: str) -> httpx.Response:
    with current_trace().span("httpx_get", attrs={"url": url}):
        return await get_with_tls_fallback(adapter, url)


def _decode(adapter, r: httpx.Response) -> str:
    """cfg.encoding 명시 시 raw bytes 를 그 charset 으로 디코드 (euc-kr/cp949 한국 사이트 — httpx 의
    charset 자동검출이 meta-only euc-kr 을 utf-8 로 오판해 mojibake 나는 걸 방지). 없으면 r.text."""
    enc = (getattr(adapter, "cfg", None) or {}).get("encoding")
    if enc:
        return r.content.decode(enc, errors="replace")
    return r.text


async def _get_text(adapter, url: str) -> str:
    r = await _get(adapter, url)
    r.raise_for_status()
    return _decode(adapter, r)


# ---------- 공유 파서 (playwright_html 도 사용) ----------

def _classes(el) -> list[str]:
    c = el.get("class")
    if c is None:
        return []
    return c.split() if isinstance(c, str) else list(c)


def _drop_ids(soup, exclude_selector: Optional[str]) -> set[int]:
    if not exclude_selector:
        return set()
    return {id(el) for el in soup.select(exclude_selector)}


def _build_post(adapter, extracted: dict, *, strategy: str) -> Optional[NoticePost]:
    pid = extracted.get("post_id")
    if pid is None or str(pid).strip() == "":
        return None
    extra = {k: v for k, v in extracted.items() if k not in {
        "post_id", "title", "url", "published_at", "author", "category", "summary", "cover_image"
    } and v is not None}
    return NoticePost(
        site=adapter.site,
        board=adapter.board,
        post_id=str(pid),
        title=str(extracted.get("title") or ""),
        url=extracted.get("url"),
        published_at=extracted.get("published_at"),
        author=extracted.get("author"),
        category=extracted.get("category"),
        summary=extracted.get("summary"),
        content_html=None,
        cover_image=extracted.get("cover_image"),
        raw={"_strategy": strategy, **extra},
    )


def parse_list_html(adapter, html: str, *, page_size: int, strategy: str = "httpx_html") -> list[NoticePost]:
    with current_trace().span("parse_list_html", attrs={"strategy": strategy, "page_size": page_size}):
        cfg = adapter.cfg
        lst = cfg["list"]
        # RSS/Atom 응답이면 XML parser. lxml HTML parser 가 `<link>`/`<guid>` 등 HTML void
        # element 를 self-closing 으로 처리 → text 빈 문자열 → posts_nonempty 0건 fail.
        soup = parse_html_or_xml(html)
        rows = soup.select(lst["row_selector"])
        dropped = _drop_ids(soup, lst.get("exclude_selector"))
        include_notices = lst.get("include_notices", True)
        notice_class_absent = lst.get("notice_class_absent")
        row_required = lst.get("row_required_selector")
        fields_spec = lst["fields"]
        ctx_base = {"site": adapter.site, "board": adapter.board}

        out: list[NoticePost] = []
        for row in rows:
            if id(row) in dropped:
                continue
            if row_required and row.select_one(row_required) is None:
                continue
            if (not include_notices) and notice_class_absent and notice_class_absent not in _classes(row):
                continue
            extracted = extract_row(root=row, fields_spec=fields_spec, context_base=ctx_base)
            post = _build_post(adapter, extracted, strategy=strategy)
            if post is None:
                continue
            out.append(post)
            if len(out) >= page_size:
                break
        return out


def _copy_post(post: NoticePost, *, content_html, url=None, overrides: Optional[dict] = None, raw_note: Optional[dict] = None) -> NoticePost:
    ov = overrides or {}
    return NoticePost(
        site=post.site,
        board=post.board,
        post_id=post.post_id,
        title=str(ov.get("title", post.title) or ""),
        url=url if url is not None else post.url,
        published_at=ov.get("published_at", post.published_at),
        author=ov.get("author", post.author),
        category=ov.get("category", post.category),
        summary=ov.get("summary", post.summary),
        content_html=content_html,
        cover_image=ov.get("cover_image", post.cover_image),
        raw={**post.raw, **(raw_note or {})},
    )


def article_url_for(adapter, post: NoticePost) -> str:
    art = adapter.cfg.get("article") or {}
    if art.get("url_template"):
        return render_template(art["url_template"], board=adapter.board, post_id=post.post_id, page=1)
    if post.url:
        return post.url
    raise ValueError(f"fetch_article: post.url 없고 article.url_template 도 없음 (post_id={post.post_id})")


def parse_article_html(adapter, html: str, *, post: NoticePost, url: str) -> NoticePost:
    with current_trace().span("parse_article_html", attrs={"url": url, "post_id": post.post_id}):
        art = adapter.cfg.get("article") or {}
        soup = parse_html(html)
        ctx = {"site": adapter.site, "board": adapter.board}
        content = None
        if art.get("content"):
            content = extract_field(art["content"], root=soup, item=None, context=ctx)
        overrides: dict = {}
        for name, spec in (art.get("enrich") or {}).items():
            v = extract_field(spec if isinstance(spec, list) else [spec], root=soup, item=None, context=ctx)
            if v is None:
                continue
            cur = getattr(post, name, None)
            if cur is None or cur == "":
                overrides[name] = v
        return _copy_post(post, content_html=content, url=url, overrides=overrides, raw_note={"fetched_url": url})


# ---------- ConfigAdapter 진입점 ----------

async def fetch_list(adapter, *, page: int = 1, page_size: int = 30) -> list[NoticePost]:
    cfg = adapter.cfg
    lst = cfg["list"]
    url, _ = build_list_url(
        url_template=lst["url_template"], pagination=lst.get("pagination"),
        board=adapter.board, page=page, page_size=page_size, page_size_max=lst.get("page_size_max"),
    )
    html = await _get_text(adapter, apply_proxy(url, cfg.get("proxy_url")))
    return parse_list_html(adapter, html, page_size=page_size, strategy="httpx_html")


async def fetch_article(adapter, post: NoticePost) -> NoticePost:
    cfg = adapter.cfg
    art = cfg.get("article") or {}
    url = article_url_for(adapter, post)
    r = await _get(adapter, apply_proxy(url, cfg.get("proxy_url")))
    skip = art.get("skip_status") or []
    if r.status_code in skip:
        return _copy_post(post, content_html=None, url=url, raw_note={"fetch_status": r.status_code, "fetch_note": "skipped status"})
    r.raise_for_status()
    return parse_article_html(adapter, _decode(adapter, r), post=post, url=url)
