"""Phase 1 / 3 / S1L: 정적 HTTP GET (httpx)."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Optional

import httpx

from .signals import classify
from .types import Result


def _save_body(out_dir: Path, name: str, body: str) -> str:
    path = out_dir / f"{name}.html"
    path.write_text(body, encoding="utf-8", errors="replace")
    return str(path)


def fetch(
    *,
    strategy: str,
    target: str,
    url: str,
    headers: dict[str, str],
    cookies: Optional[dict[str, str]] = None,
    out_dir: Path,
    body_name: str,
    baseline_blocked: bool = False,
    timeout: float = 15.0,
) -> Result:
    """동기 httpx GET.

    응답 본문을 `out_dir/{body_name}.html`에 저장하고 분류 결과를 반환.
    """
    started = time.perf_counter()
    status: Optional[int] = None
    body: Optional[str] = None
    resp_headers: dict[str, str] = {}
    final_url: Optional[str] = None
    error: Optional[str] = None
    redirected_to_login = False

    try:
        with httpx.Client(
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            r = client.get(url)
            status = r.status_code
            body = r.text
            resp_headers = {k: v for k, v in r.headers.items()}
            final_url = str(r.url)
            # 리다이렉트 체인에 login 흔적
            for hist in r.history:
                loc = hist.headers.get("location", "")
                if "login" in loc.lower() or "signin" in loc.lower():
                    redirected_to_login = True
                    break
    except Exception as e:
        error = f"{type(e).__name__}: {e}"

    duration_ms = int((time.perf_counter() - started) * 1000)

    body_path = None
    if body is not None:
        body_path = _save_body(out_dir, body_name, body)

    cls, notable = classify(
        status=status,
        body=body,
        headers=resp_headers,
        final_url=final_url,
        redirected_to_login=redirected_to_login,
        error=error,
        baseline_blocked=baseline_blocked,
    )
    return Result(
        strategy=strategy,
        target=target,
        url=url,
        final_url=final_url,
        status=status,
        duration_ms=duration_ms,
        body_path=body_path,
        headers=resp_headers,
        classification=cls,
        notable=notable,
        error=error,
    )
