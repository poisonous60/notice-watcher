"""Playwright(chromium) + stealth → 렌더된 HTML → bs4 CSS (JS 렌더/Cloudflare 보호 게시판) strategy.

adapters/arca.py 를 일반화. 파싱(HTML→NoticePost)은 httpx_html 의 parse_list_html / parse_article_html 재사용 —
즉 config 의 list.fields / article.content / row_selector 등 스키마가 httpx_html 과 동일하다. 추가 키:
  list.wait_selector       : 목록에서 이 요소가 나타날 때까지 대기(선택)
  article.wait_selector    : 본문에서 〃 (없으면 list.wait_selector 사용 안 함)
  config 최상위:
    storage_state_path     : Playwright storage_state.json 경로(로그인 세션 재사용; 파일 있으면 로드)
    headless               : 기본 true
    nav_timeout_ms / idle_timeout_ms : goto / networkidle 타임아웃(기본 30000 / 15000)
프록시(proxy_url)는 미지원(브라우저라). 이 strategy 는 playwright 패키지가 설치돼 있어야 동작.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..base_compat import NoticePost
from ._common import apply_proxy, build_list_url
from . import httpx_html as _h  # parse_list_html / parse_article_html / article_url_for 재사용


def _ua_from_headers(headers: dict) -> Optional[str]:
    for k, v in (headers or {}).items():
        if k.lower() == "user-agent":
            return v
    return None


async def open_session(adapter) -> None:
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise RuntimeError("playwright 미설치 — playwright_html strategy 사용 불가. `pip install playwright; playwright install chromium`") from e

    cfg = adapter.cfg
    headless = cfg.get("headless", True)
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=headless)
    ua = _ua_from_headers(cfg.get("headers") or {})
    ctx_kwargs: dict = {"locale": "ko-KR", "viewport": {"width": 1366, "height": 900}}
    if ua:
        ctx_kwargs["user_agent"] = ua
    ssp = cfg.get("storage_state_path")
    if ssp and Path(ssp).exists():
        ctx_kwargs["storage_state"] = str(ssp)
    context = await browser.new_context(**ctx_kwargs)
    # stealth (선택)
    try:
        from playwright_stealth import Stealth  # type: ignore
        await Stealth().apply_stealth_async(context)
    except Exception:
        pass
    # 추가 헤더(UA 제외)도 주입
    extra = {k: v for k, v in (cfg.get("headers") or {}).items() if k.lower() != "user-agent"}
    if extra:
        await context.set_extra_http_headers(extra)
    page = await context.new_page()
    adapter._pw, adapter._browser, adapter._context, adapter._page = pw, browser, context, page


async def close_session(adapter) -> None:
    for attr, closer in (("_page", "close"), ("_context", "close"), ("_browser", "close"), ("_pw", "stop")):
        obj = getattr(adapter, attr, None)
        if obj is None:
            continue
        try:
            await getattr(obj, closer)()
        except Exception:
            pass
        setattr(adapter, attr, None)


async def _goto(adapter, url: str, *, wait_selector: Optional[str] = None) -> str:
    cfg = adapter.cfg
    page = adapter._page
    nav_to = int(cfg.get("nav_timeout_ms", 30000))
    idle_to = int(cfg.get("idle_timeout_ms", 15000))
    await page.goto(url, wait_until="domcontentloaded", timeout=nav_to)
    try:
        await page.wait_for_load_state("networkidle", timeout=idle_to)
    except Exception:
        pass
    if wait_selector:
        try:
            await page.wait_for_selector(wait_selector, timeout=idle_to)
        except Exception:
            pass
    return await page.content()


async def fetch_list(adapter, *, page: int = 1, page_size: int = 30) -> list[NoticePost]:
    cfg = adapter.cfg
    lst = cfg["list"]
    url, _ = build_list_url(
        url_template=lst["url_template"], pagination=lst.get("pagination"),
        board=adapter.board, page=page, page_size=page_size, page_size_max=lst.get("page_size_max"),
    )
    if cfg.get("proxy_url"):
        # 브라우저 strategy 에선 proxy_url 무시(헤더 기반 프록시는 httpx 전용). 경고 없이 무시.
        pass
    html = await _goto(adapter, url, wait_selector=lst.get("wait_selector"))
    return _h.parse_list_html(adapter, html, page_size=page_size, strategy="playwright_html")


async def fetch_article(adapter, post: NoticePost) -> NoticePost:
    art = adapter.cfg.get("article") or {}
    url = _h.article_url_for(adapter, post)
    html = await _goto(adapter, url, wait_selector=art.get("wait_selector"))
    return _h.parse_article_html(adapter, html, post=post, url=url)
