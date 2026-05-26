"""Phase 2: Playwright headless 풀 로드 + record_har_path 트래픽 캡처.

playwright/playwright-stealth가 미설치면 `is_available() == False`로 skip 가능.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

from ._contract import validate_payload
from ._heuristic import heuristic
from .signals import classify
from .types import Classification, Result

log = logging.getLogger("probe.fetch_headless")


_MAX_CAPTURED_HTML_CHARS = max(
    10_000,
    int(os.environ.get("PROBE_HEADLESS_HTML_CHAR_LIMIT", "2000000")),
)


def _bounded_close(closeable, *, label: str, timeout_s: float = 10.0) -> None:
    """Playwright sync 객체는 생성 thread 의 greenlet 에 묶인다.

    과거에는 close 를 별도 thread 로 던져 timeout 처리를 했지만 sync API 내부 callback 이 원래
    greenlet 으로 switch 하려다 `greenlet.error: cannot switch to a different thread` 를 냈다.
    이제 headless 호출자는 register.py 의 bounded subprocess 안에서 실행되므로, close 는 같은
    thread 에서 수행하고 hang 은 부모 process timeout 이 process tree 를 kill 해 끊는다.
    """
    try:
        closeable.close()
    except Exception as e:  # noqa: BLE001
        log.warning("playwright %s failed during close: %r", label, e)


def is_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


# chromium 콜드 launch 가속 — 백그라운드 networking·번역·확장프로그램 등 끔.
# automation bit 도 함께 끔(`--disable-blink-features=AutomationControlled`) — stealth 와 보완.
_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-default-apps",
    "--disable-extensions",
    "--disable-component-extensions-with-background-pages",
    "--disable-background-networking",
    "--disable-component-update",
    # ServiceWorker 비활성화 — scripts/playwright_daemon.py 의 `_LAUNCH_ARGS` 와 동기.
    # 다른 사이트(hoyolab.com 등) 가 등록한 SW 가 context attach 시점에 CRBrowser
    # _onAttachedToTarget assertion crash 유발 → Node driver 죽고 register subprocess 600s
    # timeout. fresh launch path 에도 적용 (daemon path 는 daemon args 가 처리).
    "--disable-features=TranslateUI,ServiceWorker",
    "--disable-translate",
]


# HAR 의 XHR/fetch 후보 발견만 필요 — image/font/media/stylesheet 는 차단해서 페이지 로드 + networkidle 가속.
# stylesheet 차단은 visual 렌더만 영향, JS engine 실행과 XHR 발사는 무관 (대부분 SPA 에서 안전).
# stylesheet 는 block 안 함 — Nuxt/Next 등 SPA 가 CSS 로드 후 hydration trigger 하는
# 경우 (Radiolab 류) cards 가 DOM 에 안 박힘. 2026-05-25 직접 측정 (resource block 없이
# 15s wait → .radiolab-card 12개 박힘) 대비 probe (block + 12s wait → 0개) 차이로 확인.
# image/media/font 는 그대로 block — bandwidth/시간 절약, probe heuristic 정확도 영향 X.
_BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36"
)

_FINGERPRINT_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['ko-KR', 'ko', 'en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
window.chrome = window.chrome || { runtime: {} };
"""

_CF_INTERSTITIAL_RE = re.compile(
    r"just a moment|checking your browser|cdn-cgi/challenge-platform|__cf_chl|cf-chl-opt",
    re.IGNORECASE,
)
_TURNSTILE_RE = re.compile(r"turnstile|cf-turnstile|challenges.cloudflare.com", re.IGNORECASE)


def _context_kwargs(*, storage_state_path: Optional[Path], record_har_path: Optional[Path] = None) -> dict:
    kwargs: dict = {
        "viewport": {"width": 1365, "height": 768},
        "screen": {"width": 1365, "height": 768},
        "device_scale_factor": 1,
        "locale": "ko-KR",
        "timezone_id": "Asia/Seoul",
        "service_workers": "block",
        "user_agent": _DEFAULT_UA,
        "extra_http_headers": {
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    }
    if record_har_path is not None:
        kwargs["record_har_path"] = str(record_har_path)
        kwargs["record_har_content"] = "attach"
    if storage_state_path and storage_state_path.exists():
        kwargs["storage_state"] = str(storage_state_path)
    return kwargs


def _install_fingerprint_patch(context) -> None:
    try:
        context.add_init_script(_FINGERPRINT_INIT_SCRIPT)
    except Exception:  # noqa: BLE001
        pass


# SPA marker detection — Nuxt/Next/Vuex 등 hydration 필요 신호.
# strict: 강한 marker (next/nuxt/initial state) 1+ 또는 weak (#__nuxt/#__next id tag) 1+.
# `<div id="app">` 단독은 false-positive 흔함 — skip (Vue 일반 mount point, 정적 사이트도 사용).
# codex review (2026-05-25) 의 "3+ markers 또는 unique tag" 제안 정정: __nuxt/__next/__INITIAL_STATE__
# 같은 unique-naming marker 는 1개 만으로 SPA 신호 충분 (다른 곳에서 우연 매칭 가능성 거의 0).
_SPA_STRONG_MARKERS_RE = re.compile(
    r"(__NEXT_DATA__|__NUXT__|window\.__INITIAL_STATE__|<div\s+id=[\"']?__nuxt[\"']?|<div\s+id=[\"']?__next[\"']?)",
    re.IGNORECASE,
)


def _has_spa_hydration_marker(html: str) -> bool:
    """SPA hydration 신호 — Nuxt/Next/Vuex 의 strict marker 1+ 매칭."""
    if not html:
        return False
    return bool(_SPA_STRONG_MARKERS_RE.search(html))


def _is_cloudflare_interstitial(page) -> tuple[bool, bool]:
    """probe sync detect — 등록 1회만 거치므로 정확도 우선 (Turnstile widget 단독 body 마커 잡음).
    polling cheap-first 변형은 engine/strategies/playwright_html._is_cloudflare_interstitial_async."""
    try:
        title = page.title() or ""
    except Exception:  # noqa: BLE001
        title = ""
    try:
        html = page.content()[:120_000]
    except Exception:  # noqa: BLE001
        html = ""
    hay = f"{title}\n{page.url}\n{html}"
    return bool(_CF_INTERSTITIAL_RE.search(hay)), bool(_TURNSTILE_RE.search(hay))


def _wait_through_cloudflare_interstitial(page, *, timeout_ms: int = 30000) -> str | None:
    """Cloudflare JS interstitial can clear itself; Turnstile/captcha should not be bypassed.

    timeout_ms 30s default (2026-05-26 이전 8s). 2026 의 CF non-interactive PoW (Turnstile invisible)
    가 10~20s 걸리는 케이스 — 8s timeout 으로 통과율 손실. *조건부* — CF challenge HTML 검출 시만
    이 wait 진입 (위 _is_cloudflare_interstitial 가드). 일반 사이트는 early return → 영향 0.
    근거: research_cloudflare_findings.md §1.5 + §7.6 (무조건 30s 박지 X — 조건부만 OK)."""
    challenge, turnstile = _is_cloudflare_interstitial(page)
    if not challenge or turnstile:
        return "turnstile_present" if turnstile else None
    deadline = time.perf_counter() + (timeout_ms / 1000.0)
    while time.perf_counter() < deadline:
        try:
            page.wait_for_timeout(500)
        except Exception:  # noqa: BLE001
            break
        challenge, turnstile = _is_cloudflare_interstitial(page)
        if turnstile:
            return "turnstile_present"
        if not challenge:
            try:
                page.wait_for_load_state("domcontentloaded", timeout=1500)
            except Exception:  # noqa: BLE001
                pass
            return "cloudflare_interstitial_cleared"
    return "cloudflare_interstitial_timeout"


def _install_resource_block(context) -> None:
    def _route(route):
        try:
            if route.request.resource_type in _BLOCKED_RESOURCE_TYPES:
                route.abort()
            else:
                route.continue_()
        except Exception:  # noqa: BLE001 — route 이미 종결됐을 수 있음
            pass
    try:
        context.route("**/*", _route)
    except Exception:  # noqa: BLE001
        pass


def _wait_xhr_quiet(page, *, quiet_ms: int = 500, hard_timeout_ms: int = 2000) -> None:
    """networkidle 대체 — 마지막 XHR/fetch/document 응답 이후 quiet_ms 새 응답 없으면 종료.

    networkidle 은 광고/트래커 keepalive 로 영영 안 끝나는 사이트 많음 — 이건 *데이터* 응답
    (xhr/fetch/document) 만 카운트 → 광고 image/script 가 떠들어도 무시. 데이터 XHR 가 끝나면 즉시 종료.

    quiet_ms: 마지막 응답 이후 새 응답 없이 유지돼야 하는 시간 (기본 500ms).
    hard_timeout_ms: 어떤 경우에도 이 이상 안 기다림 (기본 2000ms).
    """
    state = {"last": time.perf_counter(), "started": time.perf_counter()}

    def _on_response(r):
        try:
            if r.request.resource_type in ("xhr", "fetch", "document"):
                state["last"] = time.perf_counter()
        except Exception:  # noqa: BLE001
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
                page.wait_for_timeout(50)
            except Exception:  # noqa: BLE001 — page 닫혔으면 즉시 종료
                break
    finally:
        try:
            page.remove_listener("response", _on_response)
        except Exception:  # noqa: BLE001
            pass


def _body_preserving_truncated_html(html: str, limit: int) -> str:
    """When head CSS exceeds the cap, keep body DOM instead of only the head prefix."""
    if len(html) <= limit:
        return html
    marker = "\n<!-- probe.truncated_html: capture limit reached -->"
    m = re.search(r"<body\b[^>]*>.*?</body>", html, re.IGNORECASE | re.DOTALL)
    if not m:
        return html[:limit] + marker
    title = ""
    tm = re.search(r"<title\b[^>]*>.*?</title>", html, re.IGNORECASE | re.DOTALL)
    if tm:
        title = tm.group(0)
    compact = f"<html><head>{title}</head>{m.group(0)}</html>"
    if len(compact) > limit:
        compact = compact[:limit]
    return compact + marker


def _capture_page_content(page) -> tuple[str, bool]:
    """DOM 전체 직렬화가 큰 SPA 에서 Python/Chromium 메모리를 같이 밀어올리지 않게 cap."""
    js = """(limit) => {
        const root = document.documentElement;
        if (!root) return {html: "", truncated: false};
        const html = root.outerHTML || "";
        if (html.length <= limit) return {html, truncated: false};
        const title = document.querySelector("title")?.outerHTML || "";
        const body = document.body?.outerHTML || "";
        if (body) {
            let compact = `<html><head>${title}</head>${body}</html>`;
            if (compact.length > limit) compact = compact.slice(0, limit);
            return {
                html: compact + "\\n<!-- probe.truncated_html: capture limit reached -->",
                truncated: true
            };
        }
        return {
            html: html.slice(0, limit) + "\\n<!-- probe.truncated_html: capture limit reached -->",
            truncated: true
        };
    }"""
    try:
        out = page.evaluate(js, _MAX_CAPTURED_HTML_CHARS) or {}
        html = str(out.get("html") or "")
        return html, bool(out.get("truncated"))
    except Exception:  # noqa: BLE001
        html = page.content()
        if len(html) > _MAX_CAPTURED_HTML_CHARS:
            return (_body_preserving_truncated_html(html, _MAX_CAPTURED_HTML_CHARS), True)
        return html, False


_DAEMON_ENDPOINT_FILE = Path(__file__).resolve().parent.parent / "output" / "playwright_daemon" / "endpoint"


def _launch_browser(p, *, headless: bool):
    channel_pref = os.environ.get("PROBE_BROWSER_CHANNEL", "chrome,msedge,bundled")
    channels = [x.strip().lower() for x in channel_pref.split(",") if x.strip()]
    for channel in channels:
        try:
            if channel in ("bundled", "chromium", "playwright"):
                return p.chromium.launch(headless=headless, args=_LAUNCH_ARGS)
            return p.chromium.launch(channel=channel, headless=headless, args=_LAUNCH_ARGS)
        except Exception as e:  # noqa: BLE001
            log.debug("browser launch failed for channel=%s: %r", channel, e)
    return p.chromium.launch(headless=headless, args=_LAUNCH_ARGS)


def _connect_or_launch(p, *, headless: bool):
    """daemon endpoint 파일 있으면 connect_over_cdp 시도, 실패 또는 없으면 fresh launch.

    daemon 사용 시 chromium cold launch (~2-3s) 회피. 단 daemon 다운/없으면 자동 fallback.
    반환: browser 객체. 호출자는 어느 path 든 browser.close() 호출.
      - connect_over_cdp 한 경우: close 가 connection 만 닫음 (daemon chromium 은 살아있음)
      - launch 한 경우: close 가 chromium 자체 종료

    Playwright 의 connect_over_cdp 는 HTTP endpoint 만 주면 internal 처리 시 trailing-slash 등으로
    timeout 나는 케이스 있음 (microsoft/playwright#35115). 대신 /json/version 에서 webSocketDebuggerUrl
    추출해 ws URL 직접 패스하는 게 안정적.
    """
    if _DAEMON_ENDPOINT_FILE.exists():
        try:
            endpoint = _DAEMON_ENDPOINT_FILE.read_text(encoding="utf-8").strip()
            if endpoint:
                import httpx as _httpx
                ver = _httpx.get(f"{endpoint}/json/version", timeout=2.0).json()
                ws = ver.get("webSocketDebuggerUrl")
                if ws:
                    # mtime touch — daemon 의 idle 타이머 reset
                    try:
                        _DAEMON_ENDPOINT_FILE.touch()
                    except Exception:  # noqa: BLE001
                        pass
                    return p.chromium.connect_over_cdp(ws, timeout=3000)
        except Exception:  # noqa: BLE001 — daemon 죽었거나 endpoint 깨짐 → fallback
            pass
    return _launch_browser(p, headless=headless)


def fetch_with_capture(
    *,
    url: str,
    out_dir: Path,
    target: str = "list",
    storage_state_path: Optional[Path] = None,
    headless: bool = True,
    baseline_blocked: bool = False,
    timeout_ms: int = 15000,
    idle_timeout_ms: int = 1000,
) -> Result:
    """Chromium 띄워 URL 로드, HAR 표준 포맷으로 트래픽 자동 기록.

    out_dir 안에 다음 산출물 생성:
      - {target}.html : 최종 outerHTML
      - {target}.screenshot.png
      - traffic.har (+ traffic.har_data/)
      - captured_headers.json : 메인 문서 요청 헤더만

    timeout_ms: page.goto(domcontentloaded) 타임아웃 (15s). domcontentloaded 는 DOM 파싱 완료
      시점이라 정상 페이지는 <3s 에 뜬다 — 15s 를 넘기는 건 사실상 anti-bot challenge/redirect 로
      매달린 것(예: Cloudflare 사이트의 글 본문 페이지가 25~30s 매달리다 빈 HTML 반환). 그 hung
      render 를 fail-fast 시키려 30s→15s 로 낮춤 (목록은 보통 2s 에 떠 영향 없음).
    idle_timeout_ms: 그 뒤 networkidle(XHR 다 잠잠해질 때까지) 추가 대기 상한(기본 2s) —
      광고/트래커가 계속 떠드는 사이트는 networkidle 이 영영 안 와서 이 상한까지 꽉 기다린다(정찰 시간의 큰 몫).
      대다수 사이트는 networkidle 이 1s 내 도달 → 2s ceiling 영향 없음. 매우 느린 SPA 의
      데이터 XHR 만 놓칠 가능성 — lite 정찰의 응답성과 트레이드오프.
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

    # Patchright = Playwright 의 stealth-patched drop-in (binary patch). 미설치 시 playwright fallback.
    # 회귀 0 — API 100% 호환. 설치 후 trace `engine: patchright` 박힘.
    try:
        from patchright.sync_api import sync_playwright  # type: ignore
        _engine_label = "patchright"
    except ImportError:
        from playwright.sync_api import sync_playwright
        _engine_label = "playwright"

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
    html_truncated = False

    try:
        with sync_playwright() as p:
            browser = None
            context = None
            try:
                browser = _connect_or_launch(p, headless=headless)
                context_kwargs = _context_kwargs(storage_state_path=storage_state_path, record_har_path=har_path)
                context = browser.new_context(**context_kwargs)
                _install_fingerprint_patch(context)
                _install_resource_block(context)
                if _has_stealth:
                    try:
                        Stealth().apply_stealth_sync(context)
                    except Exception:  # stealth 실패는 치명적 X
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
                    try:
                        response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    except Exception as ge:
                        # goto timeout 시 — CF interstitial 이 navigation 을 deadlock 시킬 수 있음 (codex
                        # P-6789 review finding 4, 2026-05-26). 현 page 에 CF challenge 가 떴는지 확인하고
                        # 떴으면 conditional wait 거친 후 content() 시도 (response 는 없을 수 있음).
                        challenge, _ = _is_cloudflare_interstitial(page)
                        if not challenge:
                            raise
                        wait_note = _wait_through_cloudflare_interstitial(page) or "goto_timeout_cf_wait"
                        response = None
                        error = f"goto_recovered_after_cf_wait: {type(ge).__name__}: {ge}"
                    if response is not None:
                        status = response.status
                        response_headers = dict(response.headers)
                        final_url = response.url
                        wait_note = _wait_through_cloudflare_interstitial(page)
                    elif "wait_note" not in locals():
                        wait_note = None
                    # 데이터 XHR/fetch 응답 끝날 때까지 대기 — networkidle 보다 빠름 (광고 image 무시)
                    _wait_xhr_quiet(page, quiet_ms=300, hard_timeout_ms=idle_timeout_ms)

                    # SPA hydration 강화 (2026-05-25 plan): strict marker (Nuxt/Next/Vuex) 감지 시
                    # 추가 quiet 대기 후 capture. Radiolab 류 (Nuxt + ad fetch flurry) 는 5초 안에
                    # quiet 안 잡히고 hydration 까지 8-12초 걸림 — 15초 wait 직접 측정에서 12 cards
                    # 박힘 확인. quiet_ms=8000 + hard_timeout=12000 으로 늘림.
                    # 비용: strict SPA marker 검출 사이트만 (251 configs 중 일부 Nuxt/Next) 최대 +12초.
                    # polling 영향 X (engine/strategies/playwright_html 가 cfg timeout 따로 사용).
                    # Radiolab list.html 의 `__nuxt` div 가 79KB 위치, `window.__NUXT__` 86KB —
                    # 50KB quick check 안 잡힘. 200KB 까지 확장 (Nuxt/Next 가 보통 body 끝에 hydration
                    # state script 박음). 비용: 1번 content() 호출 + 200KB substring 비교만.
                    spa_extra_wait_note: Optional[str] = None
                    try:
                        quick = page.content()[:200_000]
                        if _has_spa_hydration_marker(quick):
                            _wait_xhr_quiet(page, quiet_ms=8000, hard_timeout_ms=12000)
                            spa_extra_wait_note = "spa_hydration_extra_wait:8000ms"
                    except Exception:
                        pass

                    body, html_truncated = _capture_page_content(page)
                    # CMP 진단 — IAB TCF/CCPA/GPP API ping. 자동 consent 발생 X (factual probe only).
                    # 결과는 out_dir/consent.json 으로 저장 → 통계로 selector 우선순위 조정 (P-4, 2026-05-26).
                    # opt-in only — _detect_cmp 가 TCF ping 800ms + USP fallback 500ms 까지 대기.
                    # batch register (100 사이트) 누적 +1.3s × 100 = +2분. env `NW_PROBE_CMP=1` 시만 활성.
                    # codex perf review P3 (2026-05-26). polling 무관 (probe 만).
                    try:
                        _cmp = _detect_cmp(page) if os.environ.get("NW_PROBE_CMP") == "1" else None
                        if _cmp:
                            # target 별 분리 — list/article 호출이 같은 out_dir 쓰는데 단일 파일이면 overwrite.
                            # codex P-6789 review finding 6 (2026-05-26).
                            (out_dir / f"consent.{target}.json").write_text(
                                json.dumps(_cmp, ensure_ascii=False, indent=2), encoding="utf-8")
                            cmp_note = f"cmp: {_cmp.get('vendor') or _cmp.get('api')}"
                        else:
                            cmp_note = None
                    except Exception:  # noqa: BLE001
                        cmp_note = None
                    try:
                        page.screenshot(path=str(screenshot_path), full_page=False)
                    except Exception:
                        pass
                except Exception as e:
                    error = f"{type(e).__name__}: {e}"
            finally:
                # browser/context leak 방지 — new_context 실패해도 browser.close() 보장.
                # _bounded_close 로 wrap — sync_api 의 close 가 anti-bot challenge 페이지(예: google
                # /sorry/index) HAR flush 단계에서 무한 block 하는 케이스 방어. 호출자 (register.py
                # 의 자식) 의 SIGKILL 이 chromium 도 정리.
                if context is not None:
                    _bounded_close(context, label="context.close")  # HAR 저장
                if browser is not None:
                    _bounded_close(browser, label="browser.close")
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
    notable.append(f"engine: {_engine_label}")
    notable.append(f"har: {har_path.name}")
    if "wait_note" in locals() and wait_note:
        notable.append(wait_note)
    if "spa_extra_wait_note" in locals() and spa_extra_wait_note:
        notable.append(spa_extra_wait_note)
    if "cmp_note" in locals() and cmp_note:
        notable.append(cmp_note)
    if html_truncated:
        notable.append(f"html_truncated: {len(body or '')}/{_MAX_CAPTURED_HTML_CHARS} chars")
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

_CONSENT_DISMISS_JS = r"""() => {
    // Known CMP selector IDs — reject 우선(PIPA/CNIL 2025 권고: 자동 Accept = informed consent 부정).
    // 출처: duckduckgo/autoconsent (MPL-2.0) lib/cmps/{onetrust,cookiebot,trustarc,quantcast,didomi}.ts
    // — selector 문자열만 발췌 (factual data). 라이선스 의무 충족: THIRD_PARTY_NOTICES.md (repo root).
    const KNOWN_CMP_REJECT = [
        '#onetrust-reject-all-handler', '.ot-pc-refuse-all-handler',
        '#CybotCookiebotDialogBodyLevelButtonLevelOptinDeclineAll',
        '#didomi-notice-disagree-button',
        '.qc-cmp2-summary-buttons button[mode="secondary"]',
        '.iubenda-cs-reject-btn', '.cmplz-btn.cmplz-deny',
    ];
    const KNOWN_CMP_ACCEPT = [
        '#onetrust-accept-btn-handler', '#accept-recommended-btn-handler', '.js-accept-cookies',
        '#CybotCookiebotDialogBodyLevelButtonAccept', '#CybotCookiebotDialogBodyButtonAccept', '.h-dtcookie-accept',
        '#truste-consent-button', '.trustarc-agree-btn',
        '.qc-cmp2-summary-buttons button[mode="primary"]',
        '#didomi-notice-agree-button',
        '[data-testid="uc-accept-all-button"]',
        '.message-component.message-button.no-children.focusable.primary-button',
        '.cc-btn.cc-allow', '.cookie-notice-accept', '.cmplz-btn.cmplz-accept',
        '.cli_action_button.wt-cli-accept-all-btn', '#cn-accept-cookie', '.iubenda-cs-accept-btn',
    ];

    // shadow-aware querySelector — open shadow root piercing. closed shadow root 은 표준상 접근 불가 → fail.
    function queryDeep(sel, root) {
        root = root || document;
        const direct = root.querySelector(sel);
        if (direct) return direct;
        const all = root.querySelectorAll('*');
        for (const el of all) {
            if (el.shadowRoot && el.shadowRoot.mode === 'open') {
                const found = queryDeep(sel, el.shadowRoot);
                if (found) return found;
            }
        }
        return null;
    }

    const textPatterns = [
        /accept/i, /agree/i, /^ok$/i, /allow/i, /got it/i,
        /동의/, /확인/, /허용/, /수락/, /모두\s*동의/,
        /Aceptar/i, /Akzeptieren/i
    ];
    const bannerHint = /(cookie|consent|privacy|gdpr|쿠키|동의|개인정보)/i;

    function visible(el) {
        const r = el.getBoundingClientRect();
        const s = window.getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
    }
    function label(el) {
        return [
            el.innerText || el.value || "",
            el.getAttribute("aria-label") || "",
            el.id || "",
            el.className || ""
        ].join(" ");
    }
    function looksLikeDismiss(el) {
        const t = label(el);
        return textPatterns.some((re) => re.test(t));
    }
    function bannerLike(el) {
        let cur = el;
        for (let depth = 0; cur && depth < 7; depth += 1, cur = cur.parentElement) {
            const idClass = `${cur.id || ""} ${cur.className || ""}`;
            const txt = (cur.innerText || "").slice(0, 1000);
            if (bannerHint.test(idClass)) return true;
            const role = (cur.getAttribute("role") || "").toLowerCase();
            const style = window.getComputedStyle(cur);
            const rect = cur.getBoundingClientRect();
            const z = parseInt(style.zIndex || "0", 10) || 0;
            const floating = ["fixed", "sticky"].includes(style.position) || z >= 1000 || role === "dialog";
            const largeEnough = rect.width >= Math.min(320, window.innerWidth * 0.25) && rect.height >= 40;
            if (floating && largeEnough && bannerHint.test(`${idClass} ${txt}`)) return true;
        }
        return false;
    }

    let clicked = 0;

    // 정책 (research_session1_cookie_banner.md §5):
    //   reject(consent 거부) → hide(banner DOM 숨김 — 비-consent 처리) → accept(최후 fallback).
    //   자동 Accept 우선 X — PIPA 2024 / CNIL 2025-06 의 "informed consent" 정신 위반.

    // 1) Known CMP REJECT — open shadow root 도 piercing. 1개 hit 면 banner 사라짐.
    for (const sel of KNOWN_CMP_REJECT) {
        const el = queryDeep(sel);
        if (el && visible(el)) {
            try { el.click(); clicked += 1; } catch (_) {}
            if (clicked >= 1) break;
        }
    }
    // 2) reject 못 찾았으면 → banner-like 컨테이너 HIDE (display:none). consent 발생 X, accept 아님.
    //    KNOWN_CMP_ACCEPT 의 부모 트리에서 가장 가까운 banner-like 컨테이너 잡아 hide.
    if (clicked === 0) {
        for (const sel of KNOWN_CMP_ACCEPT) {
            const el = queryDeep(sel);
            if (!el || !visible(el)) continue;
            let cur = el, hid = false;
            for (let depth = 0; cur && depth < 7; depth += 1, cur = cur.parentElement) {
                const idClass = `${cur.id || ""} ${cur.className || ""}`;
                if (bannerHint.test(idClass)) {
                    try { cur.style.setProperty("display", "none", "important"); clicked += 1; hid = true; } catch (_) {}
                    break;
                }
            }
            if (hid) break;
        }
    }
    // 3) hide 도 못 했으면 → 최후 accept (rejection UI 도 banner-like 컨테이너 도 못 찾는 사이트).
    if (clicked === 0) {
        for (const sel of KNOWN_CMP_ACCEPT) {
            const el = queryDeep(sel);
            if (el && visible(el)) {
                try { el.click(); clicked += 1; } catch (_) {}
                if (clicked >= 1) break;
            }
        }
    }
    if (clicked > 0) return clicked;

    // 2) Fallback — 기존 textPatterns + bannerLike 휴리스틱 (unknown CMP / 일반 cookie banner).
    const candidates = Array.from(document.querySelectorAll(
        '[id*="cookie" i] button, [class*="cookie" i] button,' +
        '[id*="consent" i] button, [class*="consent" i] button,' +
        'button[id*="accept" i], button[id*="agree" i], button[class*="accept" i],' +
        '[aria-label*="accept" i], [aria-label*="agree" i],' +
        'button, [role="button"], input[type="button"], input[type="submit"]'
    ));
    for (const el of candidates) {
        if (clicked >= 3) break;
        if (!visible(el) || !looksLikeDismiss(el) || !bannerLike(el)) continue;
        try {
            el.click();
            clicked += 1;
        } catch (_) {}
    }
    return clicked;
}"""


# CMP API 검출 — IAB TCF v2.x · CCPA · GPP · TCF v1. ping 응답으로 vendor cmpId 추출 (factual probe only,
# 자동 consent 발생 X). 결과는 out_dir/consent.json 에 저장 → 통계로 KNOWN_CMP_*_SELECTORS 우선순위 조정.
# 근거: research_session1_cookie_banner.md §4.
_CMP_DETECT_JS = r"""
async () => {
    const tcf = await new Promise((resolve) => {
        if (typeof window.__tcfapi !== 'function') return resolve(null);
        try {
            window.__tcfapi('ping', 2, (pingReturn, success) => {
                if (!success || !pingReturn) return resolve(null);
                resolve({api: 'tcfv2', cmpId: pingReturn.cmpId, cmpLoaded: !!pingReturn.cmpLoaded,
                        cmpStatus: pingReturn.cmpStatus, gdprApplies: pingReturn.gdprApplies});
            });
            setTimeout(() => resolve(null), 800);
        } catch (e) { resolve(null); }
    });
    if (tcf) return tcf;
    const usp = await new Promise((resolve) => {
        if (typeof window.__uspapi !== 'function') return resolve(null);
        try {
            window.__uspapi('getUSPData', 1, (uspData, success) => {
                resolve(success ? {api: 'ccpa', uspString: uspData && uspData.uspString} : null);
            });
            setTimeout(() => resolve(null), 500);
        } catch (e) { resolve(null); }
    });
    if (usp) return usp;
    if (typeof window.__gpp === 'function') return {api: 'gpp'};
    if (typeof window.__cmp === 'function') return {api: 'tcfv1'};
    return null;
}
""".strip()

# IAB-registered CMP ID → vendor 이름 (자주 보이는 것). 전체 list: https://cmplist.consensu.org/
_CMP_ID_NAMES = {
    5: "Quantcast Choice", 7: "TrustArc", 10: "Cookiebot (Usercentrics)",
    28: "Sourcepoint", 91: "Didomi", 300: "OneTrust", 412: "Osano",
}


def _detect_cmp(page) -> Optional[dict]:
    """페이지의 IAB-등록 CMP 존재 검출 (TCF/CCPA/GPP). None = 없음 또는 timeout. 자동 consent 발생 X."""
    try:
        info = page.evaluate(_CMP_DETECT_JS)
    except Exception:  # noqa: BLE001
        return None
    if not info:
        return None
    if info.get("api") == "tcfv2":
        info["vendor"] = _CMP_ID_NAMES.get(info.get("cmpId"), f"unknown-id-{info.get('cmpId')}")
    return info


_CMP_FRAME_URL_HINTS = (
    "privacy-mgmt.com",         # Sourcepoint
    "fundingchoicesmessages",   # Google Funding Choices
    "cmp.quantcast.com",        # Quantcast Choice
    "consent.cookiebot.com",    # Cookiebot iframe variant
    "consent.trustarc.com",     # TrustArc
    "consensu.org",             # IAB TCF iframe
    "didomi.io",
)


# iframe reject 우선 selectors — Sourcepoint secondary / autoconsent reject affordances + text 매칭.
# 정책: 자동 accept 우선 X (PIPA 2024 / CNIL 2025-06). reject 못 찾으면 *iframe hide* 시도, 그것도
# 못 하면 최후 accept fallback.
_FRAME_REJECT_SELECTORS = (
    ".message-component.message-button.no-children.focusable.secondary-button",  # Sourcepoint secondary (reject/non-consent)
    'button[aria-label*="Reject" i]',
    'button[aria-label*="Decline" i]',
    'button[aria-label*="Refuse" i]',
    'button:has-text("Reject")',
    'button:has-text("Decline")',
    'button:has-text("Refuse")',
    'button:has-text("거부")',
    'button:has-text("나중에")',
)
_FRAME_ACCEPT_SELECTORS = (
    ".message-component.message-button.no-children.focusable.primary-button",  # Sourcepoint primary (accept)
    'button[aria-label*="Consent" i]',
    'button[aria-label*="Agree" i]',
    'button[aria-label*="Accept" i]',
    'button:has-text("Consent")',
    'button:has-text("Agree")',
    'button:has-text("Accept")',
    'button:has-text("동의")',
)


def _dismiss_consent_in_frames(page) -> int:
    """iframe CMP 처리 (Sourcepoint / Google Funding Choices / Quantcast 등 — main DOM 바깥).
    main page 는 _dismiss_consent_modals 가 page.evaluate 로 직접 처리하므로 여기서 제외.

    3단계: reject → hide(iframe element 자체) → accept (fallback). codex P-1~3 review finding 1
    (2026-05-26) — frame 처리도 reject-first 분리 의무.
    """
    dismissed = 0
    try:
        frames = list(page.frames)
    except Exception:  # noqa: BLE001
        return 0
    main = None
    try:
        main = page.main_frame
    except Exception:  # noqa: BLE001
        main = None
    for frame in frames:
        if frame is main:
            continue
        try:
            url = (frame.url or "").lower()
        except Exception:  # noqa: BLE001
            continue
        if not any(h in url for h in _CMP_FRAME_URL_HINTS):
            continue
        # 1) reject 우선
        hit = False
        for sel in _FRAME_REJECT_SELECTORS:
            try:
                loc = frame.locator(sel).first
                if loc.count() and loc.is_visible(timeout=500):
                    loc.click(timeout=2000, no_wait_after=True)
                    dismissed += 1
                    hit = True
                    break
            except Exception:  # noqa: BLE001
                continue
        # 2) reject 못 찾으면 iframe element 자체 hide (consent 발생 X).
        if not hit:
            try:
                fe = frame.frame_element()
                if fe is not None:
                    fe.evaluate("(el) => { el.style.setProperty('display', 'none', 'important'); }")
                    dismissed += 1
                    hit = True
            except Exception:  # noqa: BLE001
                pass
        # 3) hide 도 못 했으면 최후 accept fallback.
        if not hit:
            for sel in _FRAME_ACCEPT_SELECTORS:
                try:
                    loc = frame.locator(sel).first
                    if loc.count() and loc.is_visible(timeout=500):
                        loc.click(timeout=2000, no_wait_after=True)
                        dismissed += 1
                        break
                except Exception:  # noqa: BLE001
                    continue
        if dismissed >= 2:
            break
    return dismissed


def _dismiss_consent_modals(page) -> int:
    """Dismiss visible cookie/consent overlays before click probing.
    main page (KNOWN_CMP_REJECT/ACCEPT ID + queryDeep open-shadow piercing + 기존 휴리스틱)
    + iframe CMP (Sourcepoint/Google Funding Choices 등 URL hint) 둘 다 처리."""
    try:
        dismissed = int(page.evaluate(_CONSENT_DISMISS_JS) or 0)
    except Exception:  # noqa: BLE001
        dismissed = 0
    dismissed += _dismiss_consent_in_frames(page)
    if dismissed > 0:
        try:
            page.wait_for_timeout(500)
        except Exception:  # noqa: BLE001
            pass
    return dismissed


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
    idle_timeout_ms: int = 1000,
) -> tuple["Result", dict]:
    """목록 페이지를 열고 '진짜 글' 로 보이는 링크를 *클릭* 해 그 결과 페이지를 캡처한다.

    산출물: article_click.html / traffic.article_click.har / article_click.screenshot.png /
            article_click.json({requested_url, resolved_url, status, clicked_text, clicked_href, note}).
    반환: (Result(strategy="S4.click", target="article"), meta_dict).
    """
    meta: dict = {"requested_url": list_url, "resolved_url": None, "status": None,
                  "clicked_text": None, "clicked_href": None, "note": None,
                  "consent_dismissed": 0}

    def _result(cls: Classification, body_path: Optional[str], status: Optional[int], dur: int,
                notable: list[str], error: Optional[str], url: str) -> "Result":
        return Result(strategy="S4.click", target="article", url=url, status=status, duration_ms=dur,
                      body_path=body_path, classification=cls, notable=notable, error=error)

    if not is_available():
        meta["note"] = "playwright not installed"
        return (_result(Classification.METHOD_INCOMPATIBLE, None, None, 0,
                        ["playwright not installed"], "playwright not installed", list_url), meta)

    try:
        from patchright.sync_api import sync_playwright  # type: ignore
        _engine_label = "patchright"
    except ImportError:
        from playwright.sync_api import sync_playwright
        _engine_label = "playwright"
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
    html_truncated = False

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
            browser = None
            context = None
            try:
                browser = _connect_or_launch(p, headless=headless)
                ckw = _context_kwargs(storage_state_path=storage_state_path, record_har_path=har_path)
                context = browser.new_context(**ckw)
                _install_fingerprint_patch(context)
                # Phase 9b 는 stylesheet 차단 X — 클릭 visibility 검출에 영향 가능. image/font/media 만 차단.
                def _route_click(route):
                    try:
                        if route.request.resource_type in ("image", "media", "font"):
                            route.abort()
                        else:
                            route.continue_()
                    except Exception:  # noqa: BLE001
                        pass
                try:
                    context.route("**/*", _route_click)
                except Exception:  # noqa: BLE001
                    pass
                if _has_stealth:
                    try:
                        Stealth().apply_stealth_sync(context)
                    except Exception:  # noqa: BLE001
                        pass
                page = context.new_page()
                try:
                    page.goto(list_url, wait_until="domcontentloaded", timeout=timeout_ms)
                    wait_note = _wait_through_cloudflare_interstitial(page)
                    _wait_xhr_quiet(page, quiet_ms=300, hard_timeout_ms=idle_timeout_ms)
                    meta["consent_dismissed"] = _dismiss_consent_modals(page)
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
                            _wait_xhr_quiet(page, quiet_ms=300, hard_timeout_ms=idle_timeout_ms)
                            final_url = page.url
                            body, html_truncated = _capture_page_content(page)
                            try:
                                page.screenshot(path=str(screenshot_path), full_page=False)
                            except Exception:  # noqa: BLE001
                                pass
                except Exception as e:  # noqa: BLE001
                    error = f"{type(e).__name__}: {e}"
            finally:
                # browser/context leak 방지 — new_context 실패해도 browser.close() 보장.
                # _bounded_close 로 wrap — sync_api 의 close 가 anti-bot challenge 페이지(예: google
                # /sorry/index) HAR flush 단계에서 무한 block 하는 케이스 방어. 호출자 (register.py
                # 의 자식) 의 SIGKILL 이 chromium 도 정리.
                if context is not None:
                    _bounded_close(context, label="context.close")  # HAR 저장
                if browser is not None:
                    _bounded_close(browser, label="browser.close")
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
    if final_url and status is None and body is not None:
        status = 200
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
    notable.append(f"engine: {_engine_label}")
    if final_url:
        notable.append(f"clicked → {final_url[:80]}")
    if html_truncated:
        notable.append(f"html_truncated: {len(body or '')}/{_MAX_CAPTURED_HTML_CHARS} chars")
    if "wait_note" in locals() and wait_note:
        notable.append(wait_note)
    notable.append(f"har: {har_path.name}")
    if meta.get("note"):
        notable.append(meta["note"][:80])
    return (_result(cls, str(html_path) if body is not None else None, status, duration_ms,
                    notable, error, final_url or list_url), meta)
