"""Phase 2: Playwright headless 풀 로드 + record_har_path 트래픽 캡처.

playwright/playwright-stealth가 미설치면 `is_available() == False`로 skip 가능.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

from ._contract import validate_payload
from ._heuristic import heuristic
from .signals import classify
from .types import Classification, Result


def is_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def fetch_with_capture(
    *,
    url: str,
    out_dir: Path,
    target: str = "list",
    storage_state_path: Optional[Path] = None,
    headless: bool = True,
    baseline_blocked: bool = False,
    timeout_ms: int = 30000,
    idle_timeout_ms: int = 4000,
) -> Result:
    """Chromium 띄워 URL 로드, HAR 표준 포맷으로 트래픽 자동 기록.

    out_dir 안에 다음 산출물 생성:
      - {target}.html : 최종 outerHTML
      - {target}.screenshot.png
      - traffic.har (+ traffic.har_data/)
      - captured_headers.json : 메인 문서 요청 헤더만

    timeout_ms: page.goto(domcontentloaded) 타임아웃 — 페이지 자체가 떠야 하므로 넉넉히(30s).
    idle_timeout_ms: 그 뒤 networkidle(XHR 다 잠잠해질 때까지) 추가 대기 상한(기본 4s) —
      광고/트래커가 계속 떠드는 사이트는 networkidle 이 영영 안 와서 이 상한까지 꽉 기다린다(그게 정찰 시간의 큰 몫).
      4s 면 대다수 사이트의 데이터 XHR 다 뜸. 느린 SPA 의 목록 JSON 놓칠 가능성은 있지만 대시보드 응답성과 트레이드오프.
    """
    if not is_available():
        return Result(
            strategy="S4" if target == "list" else "S4.article",
            target=target,
            url=url,
            classification=Classification.METHOD_INCOMPATIBLE,
            notable=["playwright not installed"],
            error="playwright not installed",
        )

    from playwright.sync_api import sync_playwright

    try:
        from playwright_stealth import Stealth  # type: ignore
        _has_stealth = True
    except ImportError:
        _has_stealth = False

    har_path = out_dir / "traffic.har"
    if har_path.exists():
        # 같은 target에 두 번 호출(목록+본문) 가능하므로 target별로 분리
        har_path = out_dir / f"traffic.{target}.har"

    html_path = out_dir / f"{target}.html"
    screenshot_path = out_dir / f"{target}.screenshot.png"
    captured_headers_path = out_dir / f"{target}.captured_headers.json"

    started = time.perf_counter()
    status: Optional[int] = None
    body: Optional[str] = None
    response_headers: dict[str, str] = {}
    captured_nav_headers: dict[str, str] = {}
    final_url: Optional[str] = None
    error: Optional[str] = None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context_kwargs = {
                "record_har_path": str(har_path),
                "record_har_content": "attach",
                "viewport": {"width": 1280, "height": 800},
                "locale": "ko-KR",
                "user_agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            }
            if storage_state_path and storage_state_path.exists():
                context_kwargs["storage_state"] = str(storage_state_path)

            context = browser.new_context(**context_kwargs)
            if _has_stealth:
                try:
                    Stealth().apply_stealth_sync(context)
                except Exception as e:  # stealth 실패는 치명적 X
                    pass

            page = context.new_page()

            # 메인 문서 요청 헤더 캡처
            def _on_request(req):
                if req.is_navigation_request() and req.url == url:
                    nonlocal captured_nav_headers
                    try:
                        captured_nav_headers = dict(req.headers)
                    except Exception:
                        pass

            page.on("request", _on_request)

            # 메인 응답 status도 받기
            main_response = None

            def _on_response(resp):
                nonlocal main_response
                if main_response is None and resp.request.is_navigation_request():
                    main_response = resp

            page.on("response", _on_response)

            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                if response is not None:
                    status = response.status
                    response_headers = dict(response.headers)
                    final_url = response.url
                # networkidle까지 추가 대기 (XHR 캡처용) — 안 오면 idle_timeout_ms 에서 끊고 진행
                try:
                    page.wait_for_load_state("networkidle", timeout=idle_timeout_ms)
                except Exception:
                    pass

                body = page.content()
                try:
                    page.screenshot(path=str(screenshot_path), full_page=False)
                except Exception:
                    pass
            except Exception as e:
                error = f"{type(e).__name__}: {e}"

            context.close()  # HAR 저장
            browser.close()
    except Exception as e:
        error = f"{type(e).__name__}: {e}"

    duration_ms = int((time.perf_counter() - started) * 1000)

    if body is not None:
        html_path.write_text(body, encoding="utf-8", errors="replace")
    if captured_nav_headers:
        captured_headers_path.write_text(
            json.dumps(captured_nav_headers, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    cls, notable = classify(
        status=status,
        body=body,
        headers=response_headers,
        final_url=final_url,
        error=error,
        baseline_blocked=baseline_blocked,
    )
    notable.append(f"har: {har_path.name}")
    if captured_nav_headers:
        notable.append(f"captured_headers: {len(captured_nav_headers)} keys")

    return Result(
        strategy="S4" if target == "list" else "S4.article",
        target=target,
        url=url,
        status=status,
        duration_ms=duration_ms,
        body_path=str(html_path) if body is not None else None,
        headers=response_headers,
        classification=cls,
        notable=notable,
        error=error,
    )


def load_captured_headers(out_dir: Path, target: str = "list") -> dict[str, str]:
    p = out_dir / f"{target}.captured_headers.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


# --------------------------------------------------------------------------- #
# 글페이지 *클릭* 진입 — fetch_with_capture(target="article") 는 first_article_url 을 직접 GET 한다.
# 그 URL 을 직접 열면 다른 페이지로 302 되거나(클라이언트 라우트: 마비노기모바일 …/notice/View?threadId=N → /Main),
# href 가 javascript: 라 URL 자체가 없으면(다음카페 모바일) 소용없다. 이 함수는 목록에서 *실제로 클릭*했을 때 가는
# 페이지의 최종 URL/HTML/HAR 을 얻는다.
# --------------------------------------------------------------------------- #
_NAV_JUNK_RE = re.compile(
    r"(로그인|logout|login|회원가입|회원|sign\s?in|sign\s?up|글쓰기|새\s*글|글\s*작성|write|작성하기|"
    r"이전|다음|prev|next|페이지|목록보기|리스트|^\s*list\s*$|검색|search|메뉴|menu|더\s*보기|^\s*more\s*$|"
    r"닫기|close|^\s*home\s*$|^\s*홈\s*$|copyright|약관|개인정보|문의|고객센터|장바구니|cart|"
    r"마이\s*페이지|mypage|설정|settings|즐겨찾기|북마크|공유|share|신고|차단|구독|알림)",
    re.IGNORECASE,
)
_ARTICLE_HINT_RE = re.compile(r"(view|detail|article|notice|read|thread|post|bbs|board|news|content|story|/\d{2,})", re.IGNORECASE)
_ID_DATA_KEY_RE = re.compile(r"(^|[-_])(id|no|seq|article|thread|data|post|board|nid|cid|aid)", re.IGNORECASE)


@heuristic
def _score_click_link(link: dict, *, page_host: str) -> int:
    href = (link.get("href") or "").strip()
    text = (link.get("text") or "").strip()
    da = link.get("dataAttrs") or {}
    low_href, low_text = href.lower(), text.lower()
    if _NAV_JUNK_RE.search(low_text) or _NAV_JUNK_RE.search(low_href):
        return -100
    s = 0
    tl = len(text)
    if 6 <= tl <= 90:
        s += 2
    elif tl == 0 or tl > 130:
        s -= 1
    is_js = (not href) or low_href in ("#",) or low_href.startswith(("#", "javascript:"))
    if is_js:
        if any(re.search(r"\d{3,}", str(v)) for v in da.values()):
            s += 3
        if any(_ID_DATA_KEY_RE.search(str(k)) for k in da):
            s += 1
        if tl >= 6:
            s += 1
    else:
        from urllib.parse import urlsplit
        sp = urlsplit(href)
        netloc = sp.netloc
        if not netloc:                         # 상대 URL — 같은 사이트
            s += 3
        elif netloc == page_host:
            s += 3
        else:
            s -= 4                             # 다른 호스트 — 외부 링크
        if re.search(r"\d{3,}", (sp.path or "") + "?" + (sp.query or "")):
            s += 2                             # 글 ID 같은 3자리+ 숫자 (1~2자리는 보통 보드/카테고리 ID)
        if _ARTICLE_HINT_RE.search(low_href):
            s += 1
        if re.search(r"[?&](order|sort|tab|view_?type|category|filter)=", low_href):
            s -= 3                             # 정렬/탭/카테고리 파라미터 — 글 상세보다 목록/네비게이션 링크일 확률
    return s


def fetch_article_by_click(
    *,
    list_url: str,
    out_dir: Path,
    headless: bool = True,
    baseline_blocked: bool = False,
    storage_state_path: Optional[Path] = None,
    timeout_ms: int = 30000,
    idle_timeout_ms: int = 4000,
) -> tuple["Result", dict]:
    """목록 페이지를 열고 '진짜 글' 로 보이는 링크를 *클릭* 해 그 결과 페이지를 캡처한다.

    산출물: article_click.html / traffic.article_click.har / article_click.screenshot.png /
            article_click.json({requested_url, resolved_url, status, clicked_text, clicked_href, note}).
    반환: (Result(strategy="S4.click", target="article"), meta_dict).
    """
    meta: dict = {"requested_url": list_url, "resolved_url": None, "status": None,
                  "clicked_text": None, "clicked_href": None, "note": None}

    def _result(cls: Classification, body_path: Optional[str], status: Optional[int], dur: int,
                notable: list[str], error: Optional[str], url: str) -> "Result":
        return Result(strategy="S4.click", target="article", url=url, status=status, duration_ms=dur,
                      body_path=body_path, classification=cls, notable=notable, error=error)

    if not is_available():
        meta["note"] = "playwright not installed"
        return (_result(Classification.METHOD_INCOMPATIBLE, None, None, 0,
                        ["playwright not installed"], "playwright not installed", list_url), meta)

    from playwright.sync_api import sync_playwright
    from urllib.parse import urlsplit
    try:
        from playwright_stealth import Stealth  # type: ignore
        _has_stealth = True
    except ImportError:
        _has_stealth = False

    har_path = out_dir / "traffic.article_click.har"
    html_path = out_dir / "article_click.html"
    screenshot_path = out_dir / "article_click.screenshot.png"
    page_host = urlsplit(list_url).netloc

    started = time.perf_counter()
    status: Optional[int] = None
    body: Optional[str] = None
    final_url: Optional[str] = None
    error: Optional[str] = None

    # data-* 수집 *후* 안정 마커(data-probeclickidx)를 심는다 — page.evaluate 이후 DOM 이 바뀌어도(.nth(i) 가 어긋나도)
    # 마커는 그 요소를 따라가므로 page.locator('a[data-probeclickidx="i"]') 로 정확히 그 링크를 클릭한다.
    _LINK_JS = """() => Array.from(document.querySelectorAll('a')).map((a, i) => {
        const box = a.getBoundingClientRect();
        const da = {};
        for (const el of [a, a.closest('li,tr,article')]) { if (!el) continue;
            for (const at of el.attributes) if (at.name.indexOf('data-') === 0) da[at.name] = at.value; }
        a.setAttribute('data-probeclickidx', String(i));
        return { i, href: a.getAttribute('href') || '', text: (a.innerText || '').trim().slice(0, 160),
                 dataAttrs: da, visible: (box.width > 0 && box.height > 0) };
    }).filter(x => x.visible)"""

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            ckw: dict = {
                "record_har_path": str(har_path),
                "record_har_content": "attach",
                "viewport": {"width": 1280, "height": 800},
                "locale": "ko-KR",
                "user_agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                               "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
            }
            if storage_state_path and storage_state_path.exists():
                ckw["storage_state"] = str(storage_state_path)
            context = browser.new_context(**ckw)
            if _has_stealth:
                try:
                    Stealth().apply_stealth_sync(context)
                except Exception:  # noqa: BLE001
                    pass
            page = context.new_page()
            try:
                page.goto(list_url, wait_until="domcontentloaded", timeout=timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=idle_timeout_ms)
                except Exception:  # noqa: BLE001
                    pass
                links = page.evaluate(_LINK_JS) or []
                ranked = sorted(((_score_click_link(l, page_host=page_host), l) for l in links),
                                key=lambda t: t[0], reverse=True)
                if not ranked or ranked[0][0] < 3:
                    meta["note"] = f"클릭할 만한 글 링크 후보 없음 (best={ranked[0][0] if ranked else 'n/a'})"
                else:
                    _, link = ranked[0]
                    meta["clicked_text"], meta["clicked_href"] = link.get("text"), link.get("href")
                    loc = page.locator(f'a[data-probeclickidx="{int(link["i"])}"]').first
                    try:
                        loc.scroll_into_view_if_needed(timeout=3000)
                    except Exception:  # noqa: BLE001
                        pass
                    clicked = False
                    try:
                        with page.expect_navigation(wait_until="domcontentloaded", timeout=timeout_ms):
                            loc.click(timeout=8000)
                        clicked = True
                    except Exception:  # noqa: BLE001  — 클라이언트 라우팅이면 풀 네비게이션이 안 올 수 있음
                        try:
                            loc.click(timeout=8000)
                            clicked = True
                        except Exception as e:  # noqa: BLE001
                            meta["note"] = f"클릭 실패: {type(e).__name__}: {e}"
                    if clicked:
                        page.wait_for_timeout(700)           # 새 탭 생성 / 클라이언트 라우팅이 시작될 짬
                        if len(context.pages) > 1:           # target=_blank 등으로 새 탭이 떴으면 그쪽으로
                            page = context.pages[-1]
                        try:
                            page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)  # 진행 중 네비게이션 완료(이미 끝났으면 즉시)
                        except Exception:  # noqa: BLE001
                            pass
                        page.wait_for_timeout(800)           # 클라이언트 라우팅 후 본문 렌더 짬
                        try:
                            page.wait_for_load_state("networkidle", timeout=idle_timeout_ms)
                        except Exception:  # noqa: BLE001
                            pass
                        final_url = page.url
                        body = page.content()
                        try:
                            page.screenshot(path=str(screenshot_path), full_page=False)
                        except Exception:  # noqa: BLE001
                            pass
            except Exception as e:  # noqa: BLE001
                error = f"{type(e).__name__}: {e}"
            context.close()                                  # HAR 저장
            browser.close()
    except Exception as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {e}"

    duration_ms = int((time.perf_counter() - started) * 1000)
    if body is not None:
        html_path.write_text(body, encoding="utf-8", errors="replace")
    meta["resolved_url"] = final_url
    if final_url:                                            # HAR 에서 final_url 응답 status 를 best-effort 로
        try:
            har = json.loads(har_path.read_text(encoding="utf-8", errors="replace"))
            for e in reversed(((har.get("log") or {}).get("entries") or [])):
                if (e.get("request") or {}).get("url") == final_url:
                    status = (e.get("response") or {}).get("status")
                    break
        except Exception:  # noqa: BLE001
            pass
    meta["status"] = status
    # NOTE: '클릭 후 URL 이 first_article_url(=probe 가 추측한 글 URL)과 다른가' 비교는 digest.py 에서 한다
    #       (여기선 list_url 밖에 모르는데, 목록→글 클릭이 list_url 과 다른 URL 로 가는 건 당연하므로 의미 없음).
    # contract validate 를 try 블록 밖에 둠 — audit [B]: contract 위반이 OSError 와 함께 silent drop 되면 안 됨.
    validate_payload("article_click.json", meta, allow_extra=False)
    try:
        (out_dir / "article_click.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:  # 디스크 쓰기 실패만 swallow (contract 위반 아님)
        pass

    cls, notable = classify(status=status, body=body, headers={}, final_url=final_url,
                            error=error or (meta.get("note") if body is None else None),
                            baseline_blocked=baseline_blocked)
    if final_url:
        notable.append(f"clicked → {final_url[:80]}")
    notable.append(f"har: {har_path.name}")
    if meta.get("note"):
        notable.append(meta["note"][:80])
    return (_result(cls, str(html_path) if body is not None else None, status, duration_ms,
                    notable, error, final_url or list_url), meta)
