"""인식기들 공용 헬퍼. 밑줄로 시작 — auto-discovery 제외."""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def qs(url: str) -> dict:
    """URL 쿼리스트링 → dict(첫값만). 값 없는 키는 버림."""
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items() if v}
