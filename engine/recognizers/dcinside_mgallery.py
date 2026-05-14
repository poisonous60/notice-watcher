"""디시인사이드 미니갤러리 → DCInsideMGalleryAdapter."""
from __future__ import annotations

import re
from typing import Optional

from ._common import qs

NAME = "dcinside-mgallery"


def _build(m: "re.Match", url: str) -> Optional[dict]:
    gallery_id = qs(url).get("id")
    if not gallery_id:
        return None
    return {
        "version": 1, "site": "dcinside.mgallery", "board": gallery_id,
        "strategy": "handwritten", "adapter": "DCInsideMGalleryAdapter",
        "kwargs": {"gallery_id": gallery_id, "include_notices": True},
        "_slug_board": gallery_id,
        "_source_url": f"https://gall.dcinside.com/mgallery/board/lists/?id={gallery_id}",
        "_note": "디시인사이드 미니갤 — known-platform 자동 인식. 손어댑터 DCInsideMGalleryAdapter. robots Crawl-Delay 30 준수(폴링 느림).",
    }


PATTERNS = [
    (re.compile(r"//gall\.dcinside\.com/mgallery/board/(?:lists|view)/?\?", re.I), _build),
]
