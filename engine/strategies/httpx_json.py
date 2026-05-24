"""httpx + JSON API 게시판 strategy.

adapters/endfield.py, adapters/navercafe.py 의 단일-호스트 JSON 흐름을 일반화한 것.
(navercafe 의 two-host + sticky-notice 분리 흐름은 config 로 안 담겨 손으로 짠 어댑터 유지.)
"""
from __future__ import annotations

from typing import Any, Optional

import httpx

from .._http import build_async_client, get_with_tls_fallback
from ..base_compat import NoticePost
from ..extract_helpers import extract_field, extract_row, navigate_json
from ._common import apply_proxy, build_list_url, check_success, render_template
from .httpx_html import _copy_post  # 동일 구현 — 한 곳에서 관리(중복 방지)


async def open_session(adapter) -> None:
    cfg = adapter.cfg
    adapter._client = build_async_client(cfg)


async def close_session(adapter) -> None:
    client = getattr(adapter, "_client", None)
    if client is not None:
        await client.aclose()
        adapter._client = None


async def _get(adapter, url: str) -> httpx.Response:
    return await get_with_tls_fallback(adapter, url)


async def _get_json(adapter, url: str) -> Any:
    r = await _get(adapter, url)
    r.raise_for_status()
    return r.json()


async def _get_html_script_json(adapter, url: str, script_root: dict) -> Any:
    """SPA 페이지의 inline `<script id="...">` JSON island 를 payload 로 사용.

    `script_root` = {"selector": "script[id='__NEXT_DATA__']"} 식. body text 를
    JSON 으로 parse. Next.js/Nuxt SSR 처럼 article list 가 HTML 안 박혀있고 별도
    JSON XHR 없는 사이트용 (Riot LoL News 등).
    """
    import json
    from bs4 import BeautifulSoup
    r = await _get(adapter, url)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    el = soup.select_one(script_root["selector"])
    if el is None:
        raise RuntimeError(f"{adapter.site} list: script_root selector 매칭 X — {script_root['selector']!r}")
    body = el.get_text() or ""
    if not body.strip():
        raise RuntimeError(f"{adapter.site} list: script_root 내용 비어있음")
    return json.loads(body)


async def fetch_list(adapter, *, page: int = 1, page_size: int = 30) -> list[NoticePost]:
    cfg = adapter.cfg
    lst = cfg["list"]
    url, _ = build_list_url(
        url_template=lst["url_template"],
        pagination=lst.get("pagination"),
        board=adapter.board,
        page=page,
        page_size=page_size,
        page_size_max=lst.get("page_size_max"),
    )
    script_root = lst.get("script_root")
    if script_root:
        payload = await _get_html_script_json(adapter, apply_proxy(url, cfg.get("proxy_url")), script_root)
    else:
        payload = await _get_json(adapter, apply_proxy(url, cfg.get("proxy_url")))

    ok, msg = check_success(payload, lst.get("success_when"))
    if not ok:
        raise RuntimeError(f"{adapter.site} list: {msg}")

    arr = navigate_json(payload, lst["list_path"])
    if not isinstance(arr, list):
        return []

    item_path = lst.get("item_path")
    type_field = lst.get("type_field")
    type_allow = set(lst.get("type_allow") or [])
    fields_spec = lst["fields"]
    ctx_base = {"site": adapter.site, "board": adapter.board}

    out: list[NoticePost] = []
    for entry in arr:
        if type_field and type_allow:
            tv = entry.get(type_field) if isinstance(entry, dict) else None
            if tv not in type_allow:
                continue
        item = navigate_json(entry, item_path) if item_path else entry
        if item is None:
            continue
        extracted = extract_row(item=item, fields_spec=fields_spec, context_base=ctx_base)
        post = _build_post(adapter, extracted, item=item)
        if post is None:
            continue
        out.append(post)
        if len(out) >= page_size:
            break
    return out


def _build_post(adapter, extracted: dict, *, item: Any) -> Optional[NoticePost]:
    pid = extracted.get("post_id")
    if pid is None or str(pid).strip() == "":
        return None
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
        raw={"_strategy": "httpx_json", "_item": item if isinstance(item, dict) else None},
    )


async def fetch_article(adapter, post: NoticePost) -> NoticePost:
    cfg = adapter.cfg
    art = cfg.get("article") or {}
    if art.get("url_template"):
        url = render_template(art["url_template"], board=adapter.board, post_id=post.post_id, page=1)
    elif post.url:
        url = post.url
    else:
        raise ValueError(f"fetch_article: post.url 없고 article.url_template 도 없음 (post_id={post.post_id})")

    r = await _get(adapter, apply_proxy(url, cfg.get("proxy_url")))
    skip = art.get("skip_status") or []
    if r.status_code in skip:
        return _copy_post(post, content_html=None, url=url, raw_note={"fetch_status": r.status_code, "fetch_note": "skipped status"})
    r.raise_for_status()
    payload = r.json()

    ok, msg = check_success(payload, art.get("success_when"))
    if not ok:
        raise RuntimeError(f"{adapter.site} article {post.post_id}: {msg}")

    data = navigate_json(payload, art.get("data_path")) if art.get("data_path") else payload
    ctx = {"site": adapter.site, "board": adapter.board}

    content = None
    if art.get("content"):
        content = extract_field(art["content"], root=None, item=data, context=ctx)

    overrides: dict = {}
    if art.get("re_extract"):
        # endfield 식: 본문 payload(data)에서 list.fields 를 재추출해 None 아닌 값으로 덮어쓴다.
        re_ext = extract_row(item=data, fields_spec=cfg["list"]["fields"], context_base=ctx)
        for name in ("title", "published_at", "author", "category", "summary", "cover_image"):
            v = re_ext.get(name)
            if v is not None:
                overrides[name] = v
    for name, spec in (art.get("enrich") or {}).items():
        v = extract_field(spec if isinstance(spec, list) else [spec], root=None, item=data, context=ctx)
        if v is None:
            continue
        cur = getattr(post, name, None)
        if cur is None or cur == "":
            overrides[name] = v

    return _copy_post(post, content_html=content, url=url, overrides=overrides, raw_note={"fetched_url": url})
