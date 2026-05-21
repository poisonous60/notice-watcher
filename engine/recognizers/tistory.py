"""Tistory 블로그 → TistoryRssAdapter (RSS 피드 직접 파싱).

사용자가 블로그 루트, 카테고리, 태그, 또는 개별 글 URL 어느 거나 줘도 호스트(<id>.tistory.com)
추출 → 블로그 단위 등록 (RSS 가 블로그 전체 글 발행).

URL 폼:
  - https://<id>.tistory.com/
  - https://<id>.tistory.com/<num>             (개별 글, 숫자 ID)
  - https://<id>.tistory.com/entry/<slug>      (개별 글, slug ID — URL-encoded 한글 가능)
  - https://<id>.tistory.com/category/<cat>
  - https://<id>.tistory.com/tag/<tag>
  - https://<id>.tistory.com/rss               (RSS feed)

자동 파이프 실패 패턴 (probe diagnosis):
  `정적 응답이 빈 shell — Playwright 응답이 정적보다 N배 큼, row-like 요소 차이 작음 →
   strategy=playwright_html 필수` + feed_candidates>=1 (RSS 발견됨)
  → RSS 우회가 더 안정 + 본문 inline.

`www.tistory.com/` 메인 hub 은 `article_page_reject.py` 의 PATTERNS_REJECT 가 먼저 잡음
(이 인식기는 subdomain only — `[a-z0-9][a-z0-9-]*` 첫 문자 alnum + builder 가 `www`/`m` 거부).
custom domain (e.g. `<x>.com` Tistory 백엔드) 은 host 만으론 분간 불가 → 일반 파이프라인.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlsplit

NAME = "tistory"

_NOTE = ("Tistory 블로그 — known-platform 자동 인식. 손어댑터 TistoryRssAdapter 가 "
         "<host>/rss 를 직접 파싱(자동 httpx_html 은 빈 shell SPA — diagnosis rule 1 "
         "`static_vs_headless` 일관). RSS description 에 본문 inline 이라 본문 fetch 도 불요. "
         "사용자가 개별 글/카테고리/태그/루트 어느 URL 을 줘도 호스트 기준으로 블로그 단위 등록.")

_RESERVED_SUB = {"www", "m", "blog"}

_HOST_RE = re.compile(r"^https?://([a-z0-9][a-z0-9-]*)\.tistory\.com(?:/|$|\?|#)", re.I)


def _build(m: "re.Match", url: str) -> Optional[dict]:
    sub = m.group(1).lower()
    if sub in _RESERVED_SUB:
        return None
    path = urlsplit(url).path or "/"
    if path.startswith("/category/") or path.startswith("/tag/"):
        return None
    host = f"{sub}.tistory.com"
    return {
        "version": 1, "site": host, "board": sub,
        "strategy": "handwritten", "adapter": "TistoryRssAdapter",
        "kwargs": {"host": host, "timeout": 15.0},
        "_slug_board": sub,
        "_source_url": url, "_note": _NOTE,
    }


PATTERNS = [
    (_HOST_RE, _build),
]
