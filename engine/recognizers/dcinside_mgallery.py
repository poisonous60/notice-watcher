"""디시인사이드 미니갤러리 → DCInsideMGalleryAdapter."""
from __future__ import annotations

import re
from typing import Optional

from ._common import qs

NAME = "dcinside-mgallery"


_EXC_RE = re.compile(r"^[a-z_]+$")


def _build(m: "re.Match", url: str) -> Optional[dict]:
    q = qs(url)
    gallery_id = q.get("id")
    if not gallery_id:
        return None
    # exception_mode=recommend → 개념글(추천글) 탭. 빈 값이면 전체글. 단순 토큰만 허용.
    exc = q.get("exception_mode")
    exc = exc if exc and _EXC_RE.match(exc) else None
    suffix = f"_{exc}" if exc else ""

    kwargs = {"gallery_id": gallery_id, "include_notices": True}
    src = f"https://gall.dcinside.com/mgallery/board/lists/?id={gallery_id}"
    if exc:
        kwargs["exception_mode"] = exc
        src += f"&exception_mode={exc}"

    return {
        "version": 1, "site": "dcinside.mgallery", "board": gallery_id,
        "strategy": "handwritten", "adapter": "DCInsideMGalleryAdapter",
        "kwargs": kwargs,
        "_slug_board": f"{gallery_id}{suffix}",
        "_source_url": src,
        "_note": "디시인사이드 미니갤 — known-platform 자동 인식. 손어댑터 DCInsideMGalleryAdapter. robots Crawl-Delay 30 준수(폴링 느림).",
    }


PATTERNS = [
    (re.compile(r"//gall\.dcinside\.com/mgallery/board/(?:lists|view)/?\?", re.I), _build),
]
