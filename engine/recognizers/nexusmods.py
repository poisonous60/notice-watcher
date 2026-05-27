"""Nexus Mods game pages → mods 탭 (Recent Mods 정렬) 등록.

URL 패턴:
  - https://www.nexusmods.com/<game>            (게임 hub — 자동으로 mods 탭으로 이동)
  - https://www.nexusmods.com/<game>/mods/      (mods 탭 default 정렬)
  - https://www.nexusmods.com/<game>/mods/?BH=4 (Recent Mods 정렬 — 폴링 대상)

Cloudflare JS challenge 있어 playwright_html + stealth (engine 기본 적용).
board="4" (BH=4 = Recent Mods). slug = <game>.
"""
from __future__ import annotations

import re
from typing import Optional


NAME = "nexusmods"

# 단일 글 URL (mod 상세) 는 게시판 워처 대상 아님 — fall through.
# pattern 그룹 1 = <game>. mod ID 가 있으면 (`/mods/\d+`) None 반환해 일반 파이프라인으로.
_PATTERN = re.compile(
    r"//(?:www\.)?nexusmods\.com/([a-z][\w-]*?)(?:/mods/?(?:\?.*)?|/?)$",
    re.I,
)
# 단일 mod 페이지 차단 (`/<game>/mods/<id>`)
_MOD_DETAIL = re.compile(r"//(?:www\.)?nexusmods\.com/[\w-]+/mods/\d+", re.I)


def _build(m: "re.Match", url: str) -> Optional[dict]:
    if _MOD_DETAIL.search(url):
        return None
    game = m.group(1)
    if not game or game.lower() in {"mods", "users", "games", "search", "about", "robots.txt"}:
        return None
    src = f"https://www.nexusmods.com/{game}/mods/?BH=4"
    return {
        "version": 1,
        "site": "nexusmods.com",
        "board": "4",
        "_slug_board": game,
        "_source_url": src,
        "_note": (f"Nexus Mods {game} mods 탭 (BH=4 Recent Mods 정렬) — known-platform 자동 인식. "
                  "playwright_html + stealth 로 CF JS challenge 우회. 입력 URL 이 게임 hub "
                  f"(`/{game}`) 든 mods 탭이든 모두 Recent Mods 정렬 폴링 대상으로 정규화."),
        "strategy": "playwright_html",
        "disable_stealth": True,
        "headers": {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "ko-KR",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
            "Sec-CH-UA": "\"Chromium\";v=\"148\", \"Google Chrome\";v=\"148\", \"Not/A)Brand\";v=\"99\"",
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": "\"Windows\"",
            "Referer": "https://www.nexusmods.com/",
            "Origin": "https://www.nexusmods.com",
        },
        "timeout": 15,
        "nav_timeout_ms": 20000,
        "idle_timeout_ms": 12000,
        "quiet_ms": 800,
        "list": {
            "url_template": f"https://www.nexusmods.com/{game}/mods/?BH={{board}}",
            "pagination": {"kind": "query_param", "page_param": "page"},
            "wait_selector": "div.mods-grid > div[data-e2eid=\"mod-tile\"]",
            "row_selector": "div.mods-grid > div[data-e2eid=\"mod-tile\"]",
            "row_required_selector": "a[data-e2eid=\"mod-tile-title\"]",
            "include_notices": True,
            "fields": {
                "post_id": [{
                    "from": "attr",
                    "selector": "a[data-e2eid=\"mod-tile-title\"]",
                    "attr": "href",
                    "transform": [["regex_extract", "/mods/(\\d+)"]],
                }],
                "title": [{
                    "from": "css",
                    "selector": "a[data-e2eid=\"mod-tile-title\"]",
                    "text": True,
                    "transform": [["collapse_ws"]],
                }],
                "url": [{
                    "from": "attr",
                    "selector": "a[data-e2eid=\"mod-tile-title\"]",
                    "attr": "href",
                    "transform": [["urljoin", "https://www.nexusmods.com"]],
                }],
                "published_at": [{
                    "from": "attr",
                    "selector": "p[data-e2eid=\"mod-tile-uploaded\"] time",
                    "attr": "datetime",
                    "transform": [["iso8601", ["%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S%z"]]],
                }],
                "author": [{
                    "from": "css",
                    "selector": "a[data-e2eid=\"user-link\"] span",
                    "text": True,
                    "transform": [["collapse_ws"]],
                }],
                "category": [{
                    "from": "css",
                    "selector": "a[data-e2eid=\"mod-tile-category\"]",
                    "text": True,
                    "transform": [["collapse_ws"]],
                }],
                "summary": [{
                    "from": "css",
                    "selector": "div[data-e2eid=\"mod-tile-summary\"]",
                    "text": True,
                    "transform": [["collapse_ws"]],
                }],
                "cover_image": [{
                    "from": "attr",
                    "selector": "a[data-e2eid=\"mod-tile-title\"] img",
                    "attr": "src",
                    "transform": [["urljoin", "https://www.nexusmods.com"]],
                }],
            },
        },
        "article": {
            "fetch_kind": "html",
            "wait_selector": "div#mainContent",
            "content": [
                {"from": "css", "selector": "div#mainContent", "html": True},
                {"from": "css", "selector": "body > div:nth-of-type(2)", "html": True},
            ],
            "enrich": {
                "title": [{
                    "from": "css",
                    "selector": "h1",
                    "text": True,
                    "transform": [["collapse_ws"]],
                }],
            },
        },
    }


PATTERNS = [(_PATTERN, _build)]
