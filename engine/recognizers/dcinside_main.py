"""디시인사이드 *정식* 갤러리 (모바일 `m.dcinside.com/board/<id>`) → httpx_html config.

미니/마이너갤(`gall.dcinside.com/mgallery/board/...`)은 `dcinside_mgallery.py` 가 담당.
정식갤은 모바일 보드 페이지(`m.dcinside.com/board/<id>`)가 desktop 의 `tbody.listwrap2 >
tr.ub-content` 와 동일 HTML 을 정적으로 내려줘 httpx_html 로 안정 수집됨 (2026-05-20-b batch:
LLM 이 `m.dcinside.com/board/lists/?id=` desktop path 로 rewrite → mobile host 404. 인식기로
proven config 고정해 deterministic 화).

본문은 desktop view (`gall.dcinside.com/board/view/?id=<id>&no=<n>`) 에서 가져온다.
"""
from __future__ import annotations

import re
from typing import Optional

from ._common import qs

NAME = "dcinside-main"

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# 정식갤만 — `/board/<id>` (action 경로 lists/view 제외). 미니/마이너는 mgallery 인식기로.
_MOBILE_RE = re.compile(r"^https?://m\.dcinside\.com/board/(?!lists\b|view\b)([A-Za-z0-9_]+)", re.I)
# desktop 정식갤 list (mgallery 아님) — `/board/lists/?id=<id>`.
_DESKTOP_RE = re.compile(r"^https?://gall\.dcinside\.com/board/lists/?\?", re.I)


def _board_id(url: str) -> Optional[str]:
    m = _MOBILE_RE.match(url)
    if m:
        return m.group(1)
    if _DESKTOP_RE.match(url):
        return qs(url).get("id")
    return None


def _build(m: "re.Match", url: str) -> Optional[dict]:
    board = _board_id(url)
    if not board:
        return None
    return {
        "version": 1, "site": "m.dcinside.com", "board": board,
        "strategy": "httpx_html",
        "headers": {
            "User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": f"https://m.dcinside.com/board/{board}",
        },
        "timeout": 15,
        # robots Crawl-Delay 30 준수.
        "polite_sleep": {"min": 30, "max": 35},
        "list": {
            "url_template": "https://m.dcinside.com/board/{board}",
            "pagination": {"kind": "query_param", "page_param": "page"},
            "row_selector": "tbody.listwrap2 > tr.ub-content.us-post",
            "include_notices": True,
            "fields": {
                "post_id": [
                    {"from": "attr", "selector": ":self", "attr": "data-no", "match": r"^\d+$"},
                    {"from": "attr", "selector": "a[href*='no=']", "attr": "href",
                     "transform": [["regex_extract", r"[?&]no=(\d+)"]]},
                ],
                "title": [
                    {"from": "css", "selector": "td.gall_tit a", "text": True,
                     "transform": [["collapse_ws"]]},
                ],
                "url": [
                    {"from": "template",
                     "value": "https://gall.dcinside.com/board/view/?id={board}&no={post_id}&page=1"},
                ],
                "published_at": [
                    {"from": "css", "selector": "td.gall_date", "attr": "title",
                     "match": r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$",
                     "transform": [["replace", " ", "T"], ["append", "+09:00"]]},
                ],
                "author": [
                    {"from": "css", "selector": "td.gall_writer .nickname em", "text": True,
                     "transform": [["collapse_ws"]]},
                    {"from": "css", "selector": "td.gall_writer", "text": True,
                     "transform": [["collapse_ws"]]},
                ],
            },
        },
        "article": {
            "fetch_kind": "html",
            "url_template": "https://gall.dcinside.com/board/view/?id={board}&no={post_id}&page=1",
            "content": [
                {"from": "css", "selector": "div.writing_view_box", "html": True},
                {"from": "css", "selector": "div.write_div", "html": True},
                {"from": "css", "selector": "div.gallview_contents", "html": True},
                {"from": "css", "selector": "article .gallview_contents", "html": True},
            ],
            "enrich": {
                "title": [
                    {"from": "css", "selector": "h3.title_subject", "text": True,
                     "transform": [["collapse_ws"]]},
                    {"from": "css", "selector": "div.gallview_head .title_subject", "text": True,
                     "transform": [["collapse_ws"]]},
                ],
                "published_at": [
                    {"from": "css", "selector": "div.gallview_head .gall_date", "attr": "title",
                     "match": r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$",
                     "transform": [["replace", " ", "T"], ["append", "+09:00"]]},
                ],
            },
        },
        "_slug_board": board,
        "_source_url": f"https://m.dcinside.com/board/{board}",
        "_note": ("디시인사이드 정식갤 (모바일 보드 페이지) — known-platform 자동 인식. "
                  "httpx_html, robots Crawl-Delay 30 준수(폴링 느림). 본문은 desktop view."),
    }


PATTERNS = [
    (_MOBILE_RE, _build),
    (_DESKTOP_RE, _build),
]
