"""아카라이브 채널 → ArcaLiveAdapter (playwright-stealth, Cloudflare 통과)."""
from __future__ import annotations

import re
from typing import Optional

NAME = "arca-live"


def _build(m: "re.Match", url: str) -> Optional[dict]:
    channel = m.group(1)
    return {
        "version": 1, "site": "arca.live", "board": channel,
        "strategy": "handwritten", "adapter": "ArcaLiveAdapter",
        "kwargs": {"channel": channel, "include_notices": True},
        "_source_url": f"https://arca.live/b/{channel}",
        "_note": ("아카라이브 — known-platform 자동 인식. Cloudflare 보호 + JS 렌더라 손어댑터 ArcaLiveAdapter(playwright-stealth) 사용. "
                  "특정 카테고리 탭만 받고 싶으면 kwargs 에 category 추가."),
    }


PATTERNS = [
    (re.compile(r"//arca\.live/b/([^/?#]+)", re.I), _build),
]
