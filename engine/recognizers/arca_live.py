"""아카라이브 채널 → ArcaLiveAdapter (playwright-stealth, Cloudflare 통과).

쿼리 파라미터 `category` 는 *채널 내 탭* (예: `?category=공식`) — ArcaLiveAdapter 의 kwarg 으로 전달.
없으면 채널 전체. 알려지지 않은 쿼리 파라미터가 섞여 있으면 안전을 위해 None 을 반환해 일반
파이프라인(probe → gemini)으로 폴백한다 (오인 등록 방지).
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import parse_qs, urlsplit

NAME = "arca-live"

# `category` 만 의미. `p` 는 페이지(등록 시엔 채널 전체를 baseline 으로 잡으므로 무시해도 됨).
_KNOWN_QUERY_PARAMS = {"category", "p"}


def _build(m: "re.Match", url: str) -> Optional[dict]:
    channel = m.group(1)
    q = parse_qs(urlsplit(url).query, keep_blank_values=False)
    unknown = set(q) - _KNOWN_QUERY_PARAMS
    if unknown:
        # 모르는 파라미터가 있으면 fast-path 거부 → probe/gemini 경로로 폴백.
        # 아카 외 게시판 호스트가 아카로 잘못 보일 가능성은 없지만, 향후 사이트가 새 쿼리
        # 파라미터를 도입했을 때 우리가 그 의미를 모르고 무시해 잘못된 baseline 을 만드는 걸 막는다.
        return None
    kwargs: dict = {"channel": channel, "include_notices": True}
    cats = [c for c in q.get("category", []) if c]
    if len(cats) > 1:
        # 같은 키가 두 번 들어왔으면 사용자가 어느 탭을 원했는지 알 수 없음 — fast-path 거부.
        return None
    if cats:
        kwargs["category"] = cats[0]
    src = f"https://arca.live/b/{channel}"
    if "category" in kwargs:
        from urllib.parse import quote
        src = f"{src}?category={quote(kwargs['category'], safe='')}"
    return {
        "version": 1, "site": "arca.live", "board": channel,
        "strategy": "handwritten", "adapter": "ArcaLiveAdapter",
        "kwargs": kwargs,
        "_source_url": src,
        "_note": ("아카라이브 — known-platform 자동 인식. Cloudflare 보호 + JS 렌더라 손어댑터 ArcaLiveAdapter(playwright-stealth) 사용. "
                  + ("선택된 카테고리 탭(`category="
                     + kwargs.get("category", "")
                     + "`)만 폴링. 채널 전체로 바꾸려면 URL 에서 `?category=...` 빼고 재등록."
                     if "category" in kwargs else "특정 카테고리 탭만 받고 싶으면 URL 에 `?category=<탭이름>` 을 붙여 재등록.")),
    }


PATTERNS = [
    (re.compile(r"//arca\.live/b/([^/?#]+)", re.I), _build),
]
