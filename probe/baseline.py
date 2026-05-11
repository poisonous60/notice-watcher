"""Phase 0: 베이스라인 핑.

도메인 루트와 robots.txt를 가벼운 헤더로 호출해 IP/도메인 차단 여부 판정용 데이터를 모은다.
"""
from __future__ import annotations

import time
from urllib.parse import urlsplit

import httpx

from .headers import preset_h2_chrome_min
from .types import Classification, Result
from .signals import classify


def _ping(client: httpx.Client, url: str, target_label: str) -> Result:
    started = time.perf_counter()
    error = None
    status = None
    body = None
    headers: dict[str, str] = {}
    try:
        r = client.get(url)
        status = r.status_code
        headers = {k: v for k, v in r.headers.items()}
        body = r.text[:4000]  # baseline은 본문 일부만
    except Exception as e:
        error = f"{type(e).__name__}: {e}"

    duration_ms = int((time.perf_counter() - started) * 1000)
    cls, notable = classify(
        status=status, body=body, headers=headers, error=error
    )
    return Result(
        strategy=target_label,
        target="baseline",
        url=url,
        status=status,
        duration_ms=duration_ms,
        headers=headers,
        classification=cls,
        notable=notable,
        error=error,
    )


def baseline_check(target_url: str) -> dict[str, Result]:
    """B1 (/) + B2 (/robots.txt). 같은 client로 가볍게."""
    parts = urlsplit(target_url)
    root = f"{parts.scheme}://{parts.netloc}/"
    robots = f"{parts.scheme}://{parts.netloc}/robots.txt"

    headers = preset_h2_chrome_min()
    with httpx.Client(headers=headers, timeout=10.0, follow_redirects=True) as client:
        b1 = _ping(client, root, "B1")
        time.sleep(2.0)
        b2 = _ping(client, robots, "B2")

    return {"B1": b1, "B2": b2}


def is_baseline_blocked(baseline: dict[str, Result]) -> bool:
    """베이스라인이 *IP/도메인-level*로 막혔다고 의심되는지.

    Cloudflare/봇 보호로 인한 BLOCKED_BOT은 사이트 자체 정책이지 IP 차단이 아니므로
    여기서 True로 보지 않는다 (BLOCKED_BOT만 있으면 False).
    """
    classes = [r.classification for r in baseline.values()]
    if any(c == Classification.OK for c in classes):
        return False
    # 모두 BLOCKED_BOT이면 사이트가 봇 보호 중일 뿐 — IP 차단으로 단정 X
    if classes and all(c == Classification.BLOCKED_BOT for c in classes):
        return False
    return True


def baseline_status_summary(baseline: dict[str, Result]) -> str:
    """summary용 한 줄 요약."""
    parts = []
    for k, r in baseline.items():
        parts.append(f"{k}={r.status} {r.classification.value}")
    return "  ".join(parts)
