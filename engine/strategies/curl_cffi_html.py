"""curl_cffi (Chrome TLS/JA3 임퍼소네이트) + bs4 (정적 HTML 게시판) strategy.

목적: origin 자체 WAF (KR IDC NHN/Naver/WAPPLES 등) 가 Python httpx 의 TLS fingerprint
(JA3 = "Python") 만 보고 HTTP 406 / 403 던지는 사이트 통과. BoringSSL 기반 libcurl 으로
Chrome 146 / Safari 26 등 실 브라우저 TLS·HTTP/2·헤더 순서를 흉내낸다.

한계: JS 실행 X — Cloudflare cf_clearance challenge cookie 요구 사이트는 무력. 그 경우는
playwright_html (+ Patchright) 로.

parse_list_html / parse_article_html / article_url_for 는 httpx_html 의 것을 그대로 재사용.
출처: research_cloudflare_findings.md §1.4 (2026-05-26).
"""
from __future__ import annotations

from typing import Optional

from ..base_compat import NoticePost
from . import httpx_html as _hh
from ._common import apply_proxy, build_list_url


# 기본 임퍼소네이트 타깃. curl_cffi 0.7+ 는 "chrome" alias 가 최신 안정 chrome 으로 매핑.
_DEFAULT_IMPERSONATE = "chrome"


def _impersonate(adapter) -> str:
    return ((adapter.cfg or {}).get("curl_cffi") or {}).get("impersonate") or _DEFAULT_IMPERSONATE


def _timeout(adapter) -> float:
    return float(((adapter.cfg or {}).get("curl_cffi") or {}).get("timeout_s") or 15)


def _request_kwargs(adapter, url: str) -> dict:
    cfg = adapter.cfg or {}
    headers = dict(cfg.get("headers") or {})
    return {
        "url": url,
        "headers": headers,
        "impersonate": _impersonate(adapter),
        "timeout": _timeout(adapter),
        "allow_redirects": True,
    }


# ---------- 세션 ----------

async def open_session(adapter) -> None:
    # curl_cffi 0.7+ 는 sync · async 둘 다 제공. 우리는 async strategy 인터페이스라 AsyncSession 사용.
    # 미설치 시 명확한 에러 — register/probe 가 strategy 선택 단계에서 잡는다.
    try:
        from curl_cffi.requests import AsyncSession  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "curl-cffi 미설치 — curl_cffi_html strategy 사용 불가. `pip install curl-cffi`"
        ) from e
    adapter._curl_session = AsyncSession(impersonate=_impersonate(adapter), timeout=_timeout(adapter))


async def close_session(adapter) -> None:
    sess = getattr(adapter, "_curl_session", None)
    if sess is None:
        return
    try:
        await sess.close()
    except Exception:  # noqa: BLE001
        pass
    adapter._curl_session = None


async def _get_text(adapter, url: str) -> str:
    sess = getattr(adapter, "_curl_session", None)
    if sess is None:
        # session 재오픈 fallback — adapter 가 close_session 후 fetch 호출하는 잘못된 순서 방어.
        await open_session(adapter)
        sess = adapter._curl_session
    cfg = adapter.cfg or {}
    headers = dict(cfg.get("headers") or {})
    resp = await sess.get(url, headers=headers, allow_redirects=True)
    if resp.status_code >= 400:
        raise RuntimeError(f"curl_cffi GET {url} → HTTP {resp.status_code}")
    enc = cfg.get("encoding")
    if enc:
        return resp.content.decode(enc, errors="replace")
    return resp.text


# ---------- ConfigAdapter 진입점 ----------

async def fetch_list(adapter, *, page: int = 1, page_size: int = 30) -> list[NoticePost]:
    cfg = adapter.cfg
    lst = cfg["list"]
    url, _ = build_list_url(
        url_template=lst["url_template"], pagination=lst.get("pagination"),
        board=adapter.board, page=page, page_size=page_size, page_size_max=lst.get("page_size_max"),
    )
    html = await _get_text(adapter, apply_proxy(url, cfg.get("proxy_url")))
    return _hh.parse_list_html(adapter, html, page_size=page_size, strategy="curl_cffi_html")


async def fetch_article(adapter, post: NoticePost) -> NoticePost:
    cfg = adapter.cfg
    art = cfg.get("article") or {}
    url = _hh.article_url_for(adapter, post)
    sess = getattr(adapter, "_curl_session", None)
    if sess is None:
        await open_session(adapter)
        sess = adapter._curl_session
    headers = dict(cfg.get("headers") or {})
    resp = await sess.get(apply_proxy(url, cfg.get("proxy_url")), headers=headers, allow_redirects=True)
    skip = art.get("skip_status") or []
    if resp.status_code in skip:
        return _hh._copy_post(post, content_html=None, url=url,
                              raw_note={"fetch_status": resp.status_code, "fetch_note": "skipped status"})
    if resp.status_code >= 400:
        raise RuntimeError(f"curl_cffi GET article {url} → HTTP {resp.status_code}")
    enc = cfg.get("encoding")
    body = resp.content.decode(enc, errors="replace") if enc else resp.text
    return _hh.parse_article_html(adapter, body, post=post, url=url)
