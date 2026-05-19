"""Phase 4: 헤드풀 Playwright + storage_state. LOGIN_REQUIRED 자동 트리거."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from .signals import classify
from .types import Classification, Result


def is_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def ensure_login_and_fetch(
    *,
    url: str,
    slug: str,
    state_path: Path,
    out_dir: Path,
    timeout_ms: int = 60000,
) -> Result:
    """state 파일이 있으면 로드, 없으면 헤드풀로 띄워 사용자 로그인 → state 저장 → 같은 URL 진입."""
    if not is_available():
        return Result(
            strategy="S5",
            target="list",
            url=url,
            classification=Classification.METHOD_INCOMPATIBLE,
            notable=["playwright not installed"],
        )

    from playwright.sync_api import sync_playwright

    started = time.perf_counter()
    status: Optional[int] = None
    body: Optional[str] = None
    error: Optional[str] = None
    resp_headers: dict[str, str] = {}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            ctx_kwargs = {
                "viewport": {"width": 1280, "height": 800},
                "locale": "ko-KR",
                "service_workers": "block",  # SW assertion crash 차단 — fetch_headless.py 참조.
            }
            if state_path.exists():
                ctx_kwargs["storage_state"] = str(state_path)
            context = browser.new_context(**ctx_kwargs)
            page = context.new_page()

            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=timeout_ms)
            except Exception:
                pass

            html = page.content()
            need_login = (
                "로그인" in html[:5000]
                or "login" in (page.url or "").lower()
                or "<input" in html and "type=\"password\"" in html
            )

            if need_login:
                print(f"\n[{slug}] 로그인이 필요합니다.")
                print("    헤드풀 브라우저가 떠 있습니다. 로그인 완료 후 콘솔에서 엔터를 눌러주세요.")
                input("    [엔터를 눌러 진행]")
                state_path.parent.mkdir(parents=True, exist_ok=True)
                context.storage_state(path=str(state_path))
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=timeout_ms)
                except Exception:
                    pass
                html = page.content()

            response = None
            # 마지막 메인 응답을 명시적으로 받지는 않음 — page.content() 길이로 OK 판정.
            body = html
            status = 200 if html else None

            (out_dir / "s5.html").write_text(body or "", encoding="utf-8", errors="replace")
            context.storage_state(path=str(state_path))  # 최신 쿠키 갱신
            context.close()
            browser.close()
    except Exception as e:
        error = f"{type(e).__name__}: {e}"

    duration_ms = int((time.perf_counter() - started) * 1000)
    cls, notable = classify(status=status, body=body, headers=resp_headers, error=error)
    return Result(
        strategy="S5",
        target="list",
        url=url,
        status=status,
        duration_ms=duration_ms,
        body_path=str(out_dir / "s5.html") if body else None,
        headers=resp_headers,
        classification=cls,
        notable=notable,
        error=error,
    )


def cookies_from_state(state_path: Path, target_url: str) -> dict[str, str]:
    """storage_state.json에서 target_url 도메인 쿠키만 추출."""
    if not state_path.exists():
        return {}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    from urllib.parse import urlsplit
    host = urlsplit(target_url).netloc
    out: dict[str, str] = {}
    for c in data.get("cookies", []):
        cookie_domain = (c.get("domain") or "").lstrip(".")
        if cookie_domain and (host == cookie_domain or host.endswith("." + cookie_domain)):
            out[c["name"]] = c.get("value", "")
    return out
