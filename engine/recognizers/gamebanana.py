"""GameBanana game hub page → SubmissionsListModule (mods 섹션) 만 폴링.

URL: https://gamebanana.com/games/<id>

게임 hub 페이지에 여러 RecordsGrid 섹션 있음 (mods/articles/threads/sounds/sub-games).
agentic 가 어느 grid 잡냐가 운이라 결정 selector 박음 = `module#SubmissionsListModule`
안의 RecordsGrid 만. post_id 추출도 `a.Name[href*='/mods/']` 로 mod 카드 한정.

CF challenge — playwright_html + disable_stealth (playwright_stealth DNS race 회피).
"""
from __future__ import annotations

import re
from typing import Optional


NAME = "gamebanana"

# games/<id> 매칭. mods/articles/threads 등 sub-resource 는 게시판 워처 대상 아님.
_PATTERN = re.compile(
    r"//(?:www\.)?gamebanana\.com/games/(\d+)/?$",
    re.I,
)


def _build(m: "re.Match", url: str) -> Optional[dict]:
    game_id = m.group(1)
    src = f"https://gamebanana.com/games/{game_id}"
    return {
        "version": 1,
        "site": "gamebanana.com",
        "board": game_id,
        "_slug_board": game_id,
        "_source_url": src,
        "_note": (f"GameBanana games/{game_id} hub — SubmissionsListModule(mods 섹션)만 폴링. "
                  "다른 RecordsGrid(articles/threads/sub-games) 잡지 않게 scope 강제. "
                  "playwright_html + disable_stealth (DNS race 회피)."),
        "strategy": "playwright_html",
        "disable_stealth": True,
        "headers": {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "ko-KR,en;q=0.9",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
            "Sec-CH-UA": "\"Chromium\";v=\"148\", \"Google Chrome\";v=\"148\", \"Not/A)Brand\";v=\"99\"",
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": "\"Windows\"",
            "Referer": "https://gamebanana.com/",
        },
        "timeout": 15,
        "nav_timeout_ms": 15000,
        "idle_timeout_ms": 4000,
        "quiet_ms": 300,
        "list": {
            "url_template": f"https://gamebanana.com/games/{{board}}",
            "pagination": {"kind": "none"},
            "wait_selector": "module#SubmissionsListModule div.RecordsGrid > div.Record",
            "row_selector": "module#SubmissionsListModule div.RecordsGrid > div.Record",
            "row_required_selector": "a.Name[href*='/mods/']",
            "include_notices": True,
            "fields": {
                "post_id": [{
                    "from": "attr",
                    "selector": "a.Name[href*='/mods/']",
                    "attr": "href",
                    "transform": [["regex_extract", "/mods/(\\d+)"]],
                }, {
                    "from": "attr",
                    "selector": "a.Preview[href*='/mods/']",
                    "attr": "href",
                    "transform": [["regex_extract", "/mods/(\\d+)"]],
                }],
                "title": [{
                    "from": "css",
                    "selector": "a.Name",
                    "text": True,
                    "transform": [["collapse_ws"]],
                }],
                "url": [{
                    "from": "attr",
                    "selector": "a.Name[href*='/mods/']",
                    "attr": "href",
                    "transform": [["urljoin", "https://gamebanana.com"]],
                }],
                "author": [{
                    "from": "css",
                    "selector": "a.Submitter, span.Submitter, .Authors a",
                    "text": True,
                    "transform": [["collapse_ws"]],
                }],
                "cover_image": [{
                    "from": "attr",
                    "selector": "img[src*='/img/']",
                    "attr": "src",
                    "transform": [["urljoin", "https://gamebanana.com"]],
                }],
            },
        },
        "article": {
            "fetch_kind": "json",
            "url_template": "https://gamebanana.com/apiv12/Mod/{post_id}/ProfilePage",
            "content": [
                {"from": "json", "path": ["_sText"]},
            ],
            "enrich": {
                "title": [{"from": "json", "path": ["_sName"]}],
                "author": [{"from": "json", "path": ["_aSubmitter", "_sName"]}],
            },
        },
    }


PATTERNS = [(_PATTERN, _build)]
