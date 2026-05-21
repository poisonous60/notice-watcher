"""XenForo 포럼 → 전역 RSS (`<base>/forums/-/index.rss`) httpx_html config.

URL 폼 (recognizer 직접 매칭):
  - https://<host>/forums/-/index.rss   (XenForo 전역 RSS 직접 URL)
  - https://<host>/whats-new/posts/     (XenForo 최근 글 페이지 — RSS 로 매핑)

root 도메인(`https://www.watchuseek.com/`)은 URL 만으론 XenForo 판정 불가(모든 root 매칭 시
false-positive 폭발) → `probe/extract.py:detect_xenforo_platform` 가 probe *후* 렌더 HTML 의
`<html id="XF">` / `XF.config` 마커로 봉합 (Discourse 와 같은 구조). register.py 가 그 신호로
build_config 호출.

왜 RSS:
  XenForo 글 목록 페이지(`/whats-new/posts/`, 서브포럼)는 Cloudflare 앞단 + JS 라 httpx 가
  ReadTimeout / 빈 DOM. 하지만 전역 RSS `<base>/forums/-/index.rss` 는 Cloudflare 가 허용하는
  경우가 많아(wordreference·hardforum 확인: 200, item 40~50건) httpx 로 안정 수집된다. RSS item =
  guid(thread id) · title · link · pubDate(RFC822) · content:encoded(본문).

오인 매칭 안전망:
  RSS 가 404(비표준 경로 — eevblog `/forum/`)·빈 목록·차단이면 fetch_list 0건 → register.py 의
  `register_recognized` 가 일반 파이프라인으로 폴백 (cfg discard). detect 마커는 false-positive ~0.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlsplit

NAME = "xenforo"

_NOTE = ("XenForo 포럼 — known-platform 자동 인식. 전역 RSS `<base>/forums/-/index.rss` 를 "
         "httpx_html(XML) 로 수집 (guid=thread id, title, link, pubDate). 글 목록 페이지는 "
         "Cloudflare/JS 라 httpx 불가지만 RSS 는 허용되는 경우가 많음.")


# XenForo route 세그먼트 — install path 끝 표지. 글 목록·thread·RSS 가 install root 바로 밑에 옴.
# 첫 매칭 세그먼트 *앞* 까지가 install path (서브폴더 설치 — 예: xenforo.com/community).
_XF_ROUTE_SEGMENTS = frozenset({
    "forums", "threads", "whats-new", "members", "posts", "find-new",
    "watched", "search", "login", "register", "account", "conversations",
    "help", "tags", "media", "resources", "online", "index.rss",
})


def _install_path(path: str) -> str:
    """URL path → XenForo install path (서브폴더 설치 지원). 첫 알려진 route 세그먼트 앞까지.
    `/community/forums/-/index.rss` → `/community`. `/whats-new/posts/` → ``. `/` → ``."""
    segs = [s for s in (path or "").split("/") if s]
    keep = []
    for s in segs:
        if s.lower() in _XF_ROUTE_SEGMENTS:
            break
        keep.append(s)
    return ("/" + "/".join(keep)) if keep else ""


def build_config(base_url: str) -> Optional[dict]:
    """`https://<host>[/<install>]` → XenForo 전역 RSS httpx_html config. recognizer(RSS/whats-new
    URL)와 register.py 의 probe-후 detect_xenforo_platform 신호 양쪽이 공유. base_url 의 path 에서
    install path 보존 (서브폴더 설치 — xenforo.com/community RSS at /community/forums/-/index.rss)."""
    parts = urlsplit(base_url)
    host = (parts.netloc or "").strip().lower()
    if not host or "." not in host:
        return None
    install = _install_path(parts.path or "")
    base = f"{parts.scheme or 'https'}://{host}{install}"
    return {
        "version": 1,
        "site": host,
        "board": "whats-new",
        "strategy": "httpx_html",
        "list": {
            "url_template": f"{base}/forums/-/index.rss",
            "pagination": {"kind": "none"},
            "row_selector": "channel > item",
            "include_notices": True,
            "fields": {
                "post_id": [
                    {"from": "css", "selector": "guid", "text": True,
                     "transform": [["collapse_ws"], ["strip"]]},
                ],
                "title": [
                    {"from": "css", "selector": "title", "text": True,
                     "transform": [["collapse_ws"]]},
                ],
                "url": [
                    {"from": "css", "selector": "link", "text": True,
                     "transform": [["collapse_ws"], ["strip"]]},
                ],
                "published_at": [
                    {"from": "css", "selector": "pubDate", "text": True,
                     "transform": [["collapse_ws"], ["iso8601", ["%a, %d %b %Y %H:%M:%S %z"]]]},
                ],
            },
        },
        "article": {"fetch_kind": "html", "content": [], "body_empty_acceptable": True},
        "_slug_board": f"{host}{install}",
        "_source_url": f"{base}/forums/-/index.rss",
        "_note": _NOTE,
    }


def _build(m: "re.Match", url: str) -> Optional[dict]:
    # full url 전달 — build_config 가 path 에서 install path 보존 (서브폴더 설치).
    return build_config(url)


# XenForo-distinctive URL paths (root 도메인은 detect_xenforo_platform 가 봉합).
# install path prefix (`/community` 등) 허용 — `(?:/[\w-]+)*?` 가 route 세그먼트 앞 서브폴더 흡수.
_RSS_RE = re.compile(r"^https?://[^/?#]+(?:/[\w-]+)*?/forums/-/index\.rss\b", re.I)
_WHATSNEW_RE = re.compile(r"^https?://[^/?#]+(?:/[\w-]+)*?/whats-new/posts/?(?:\?|#|$)", re.I)

PATTERNS = [
    (_RSS_RE, _build),
    (_WHATSNEW_RE, _build),
]
