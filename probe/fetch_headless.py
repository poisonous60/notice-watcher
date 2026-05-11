"""Phase 2: Playwright headless 풀 로드 + record_har_path 트래픽 캡처.

playwright/playwright-stealth가 미설치면 `is_available() == False`로 skip 가능.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from .signals import classify
from .types import Result


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
) -> Result:
    """Chromium 띄워 URL 로드, HAR 표준 포맷으로 트래픽 자동 기록.

    out_dir 안에 다음 산출물 생성:
      - {target}.html : 최종 outerHTML
      - {target}.screenshot.png
      - traffic.har (+ traffic.har_data/)
      - captured_headers.json : 메인 문서 요청 헤더만
    """
    if not is_available():
        return Result(
            strategy="S4" if target == "list" else "S4.article",
            target=target,
            url=url,
            classification=__import__("probe.types", fromlist=["Classification"]).Classification.METHOD_INCOMPATIBLE,
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
                # networkidle까지 추가 대기 (XHR 캡처용)
                try:
                    page.wait_for_load_state("networkidle", timeout=timeout_ms)
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
