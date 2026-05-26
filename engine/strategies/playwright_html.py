"""Playwright(chromium) + stealth → 렌더된 HTML → bs4 CSS (JS 렌더/Cloudflare 보호 게시판) strategy.

adapters/arca.py 를 일반화. 파싱(HTML→NoticePost)은 httpx_html 의 parse_list_html / parse_article_html 재사용 —
즉 config 의 list.fields / article.content / row_selector 등 스키마가 httpx_html 과 동일하다. 추가 키:
  list.wait_selector       : 목록에서 이 요소가 나타날 때까지 대기(선택)
  article.wait_selector    : 본문에서 〃 (없으면 list.wait_selector 사용 안 함)
  config 최상위:
    storage_state_path     : Playwright storage_state.json 경로(로그인 세션 재사용; 파일 있으면 로드)
    headless               : 기본 true
    nav_timeout_ms / idle_timeout_ms : goto / XHR-quiet hard cap (기본 15000 / 2000)
                                       — domcontentloaded 는 정상 페이지 <3s. 15s 넘기는 건 anti-bot
                                         challenge/redirect 로 매달린 것 → fail-fast (register 검증·폴링
                                         양쪽의 hung-render 비용 차단). 더 느린 사이트는 config 로 상향.
    quiet_ms                          : XHR/fetch/document 무응답 임계 (기본 500ms; 이 시간 새 데이터 응답 0이면 즉시 종료)
프록시(proxy_url)는 미지원(브라우저라). 이 strategy 는 playwright 패키지가 설치돼 있어야 동작.
"""
from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Optional

from ..base_compat import NoticePost
from ._common import apply_proxy, build_list_url
from . import httpx_html as _h  # parse_list_html / parse_article_html / article_url_for 재사용


# Cloudflare interstitial detection — runtime polling 도 probe 와 같은 challenge 통과 wait 필요.
# probe/fetch_headless.py 의 동일 regex sync 버전 미러링 — codex P-6789 review finding 3 (2026-05-26).
_CF_INTERSTITIAL_RE = re.compile(
    r"just a moment|checking your browser|cdn-cgi/challenge-platform|__cf_chl|cf-chl-opt",
    re.IGNORECASE,
)
_TURNSTILE_RE = re.compile(r"turnstile|cf-turnstile|challenges.cloudflare.com", re.IGNORECASE)


async def _is_cloudflare_interstitial_async(page) -> tuple[bool, bool]:
    """cheap-first CF detect — title + page.url 매번 검사, 매칭 시만 page.content() 호출.

    이전: 매 polling 마다 page.content() 호출 → 48/256 configs (playwright_html) × N fetches 누적
    DOM copy 비용 (codex perf review P1, 2026-05-26). 정상 사이트는 title/url 검사 +가벼운 regex
    miss → content() 안 함 → 매 fetch ~ms 비용.
    """
    try:
        title = await page.title() or ""
    except Exception:  # noqa: BLE001
        title = ""
    cheap_hay = f"{title}\n{page.url}"
    if not _CF_INTERSTITIAL_RE.search(cheap_hay) and not _TURNSTILE_RE.search(cheap_hay):
        return False, False
    # cheap signal hit — body 까지 검사
    try:
        html = (await page.content())[:120_000]
    except Exception:  # noqa: BLE001
        html = ""
    hay = f"{cheap_hay}\n{html}"
    return bool(_CF_INTERSTITIAL_RE.search(hay)), bool(_TURNSTILE_RE.search(hay))


async def _wait_through_cloudflare_interstitial_async(page, *, timeout_ms: int = 30000) -> str:
    """polling 시 CF JS interstitial 통과 대기. 반환:
        "none"      — CF challenge 자체 없음 (정상 사이트)
        "cleared"   — challenge 검출 후 wait 안에 통과
        "timeout"   — challenge 검출, wait 안에 통과 못 함 (caller 가 raise 추천)
        "turnstile" — Turnstile interactive — 통과 시도 X (caller 가 cap_blocked 처리)
    """
    challenge, turnstile = await _is_cloudflare_interstitial_async(page)
    if not challenge:
        return "none"
    if turnstile:
        return "turnstile"
    deadline = time.perf_counter() + (timeout_ms / 1000.0)
    while time.perf_counter() < deadline:
        try:
            await page.wait_for_timeout(500)
        except Exception:  # noqa: BLE001
            return "timeout"
        challenge, turnstile = await _is_cloudflare_interstitial_async(page)
        if turnstile:
            return "turnstile"
        if not challenge:
            return "cleared"
    return "timeout"


class CloudflareUnsolvedError(RuntimeError):
    """CF challenge 가 wait 시간 안에 통과 안 됨, 또는 Turnstile interactive 검출."""


async def _wait_xhr_quiet(page, *, quiet_ms: int = 500, hard_timeout_ms: int = 2000) -> None:
    """networkidle 대체 — XHR/fetch/document 응답 quiet_ms 무응답이면 종료, hard_timeout_ms 절대 상한.

    networkidle 은 광고/트래커 keepalive 로 영영 안 끝나는 사이트(Google search, 뉴스, 포털)에서
    idle_timeout 끝까지 박힘 — 6번 fetch × 15s = validate 가 90s 까지 늘어남.
    데이터 응답(xhr/fetch/document) 만 카운트하면 광고 image/script 떠들어도 무시 → 진짜 데이터 끝나면 즉시 종료.
    probe/fetch_headless.py 의 sync 버전을 async 로 포팅 (commit 2af5d1f 참조).
    """
    state = {"last": time.perf_counter(), "started": time.perf_counter()}

    def _on_response(r):
        try:
            if r.request.resource_type in ("xhr", "fetch", "document"):
                state["last"] = time.perf_counter()
        except Exception:
            pass

    page.on("response", _on_response)
    quiet_s = quiet_ms / 1000.0
    hard_s = hard_timeout_ms / 1000.0
    try:
        while True:
            now = time.perf_counter()
            if now - state["started"] > hard_s:
                break
            if now - state["last"] > quiet_s:
                break
            try:
                await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                raise
            except Exception:
                break  # page 닫혔거나 context teardown — hard cap 까지 폴링하지 말고 즉시 종료
    finally:
        try:
            page.remove_listener("response", _on_response)
        except Exception:
            pass


def _ua_from_headers(headers: dict) -> Optional[str]:
    for k, v in (headers or {}).items():
        if k.lower() == "user-agent":
            return v
    return None


async def open_session(adapter) -> None:
    # Patchright = Playwright 의 stealth-patched drop-in. 미설치 시 playwright fallback.
    # adapter._engine_label 에 기록 → polling trace 가 어느 엔진 썼는지 분리 측정 가능.
    try:
        from patchright.async_api import async_playwright  # type: ignore
        adapter._engine_label = "patchright"
    except ImportError:
        try:
            from playwright.async_api import async_playwright
            adapter._engine_label = "playwright"
        except ImportError as e:
            raise RuntimeError("playwright 미설치 — playwright_html strategy 사용 불가. `pip install playwright; playwright install chromium` (또는 patchright + `patchright install chromium`)") from e

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
    # CF cache — 같은 polling cycle 안 첫 _goto 가 CF challenge 통과(or none) 했으면 이후 _goto 는
    # CF wait skip. context cookies 가 같은 cycle 안 cf_clearance 보관 → 재검사 불필요. 다음 cycle
    # open_session 새로 호출되며 cache reset (codex perf review P1, 2026-05-26).
    adapter._cf_state = "unchecked"   # unchecked → none|cleared (skip) or turnstile (raise) or timeout (raise)


async def close_session(adapter) -> None:
    # 각 close/stop 5s wall cap — 1단계 hang 이 다음 단계 cleanup 막지 않게 (ADR 0016 P+).
    # cancel·playwright driver pipe 끊김 등에서도 best-effort 로 4 핸들 다 None 처리.
    # open_session mid-hang 케이스: __aenter__ 가 partial state 만 채우고 raise/cancel 되면
    # ConfigAdapter __aexit__ 가 호출 안 됨 → close_session 도 안 불림. 그 leak 은 systemd
    # `KillMode=mixed` (deploy/notice-poll.service, ADR 0016 P4) 가 외곽에서 정리.
    for attr, closer in (("_page", "close"), ("_context", "close"), ("_browser", "close"), ("_pw", "stop")):
        obj = getattr(adapter, attr, None)
        if obj is None:
            continue
        try:
            await asyncio.wait_for(getattr(obj, closer)(), timeout=5.0)
        except BaseException:  # noqa: BLE001 — Cancel 포함 다 흡수, 다음 핸들 close 진행
            pass
        setattr(adapter, attr, None)


async def _goto(adapter, url: str, *, wait_selector: Optional[str] = None) -> str:
    cfg = adapter.cfg
    page = adapter._page
    nav_to = int(cfg.get("nav_timeout_ms", 15000))
    idle_to = int(cfg.get("idle_timeout_ms", 2000))
    quiet_to = int(cfg.get("quiet_ms", 500))
    cf_wait_to = int(cfg.get("cf_wait_timeout_ms", 30000))
    await page.goto(url, wait_until="domcontentloaded", timeout=nav_to)
    # CF wait — adapter-level cache. unchecked 면 detect+wait, none|cleared 면 skip,
    # turnstile|timeout 이면 raise (caller 가 적절히 처리).
    cf_state = getattr(adapter, "_cf_state", "unchecked")
    if cf_state == "unchecked":
        verdict = await _wait_through_cloudflare_interstitial_async(page, timeout_ms=cf_wait_to)
        adapter._cf_state = verdict
        if verdict == "turnstile":
            raise CloudflareUnsolvedError(f"Cloudflare Turnstile interactive on {url} — 자동 통과 X (cap_blocked).")
        if verdict == "timeout":
            raise CloudflareUnsolvedError(f"Cloudflare interstitial 통과 못 함 (>{cf_wait_to}ms) on {url} — cap_blocked 의심.")
    elif cf_state in ("turnstile", "timeout"):
        # 같은 cycle 안 이전 _goto 가 unsolvable CF — 후속 _goto 도 같은 host 이므로 즉시 raise.
        raise CloudflareUnsolvedError(f"adapter cf_state={cf_state!r} (이전 _goto 에서 결정) on {url}")
    # cf_state in ("none", "cleared") → wait skip (cookie 공유로 재검사 불필요)
    await _wait_xhr_quiet(page, quiet_ms=quiet_to, hard_timeout_ms=idle_to)
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
