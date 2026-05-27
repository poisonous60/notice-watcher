"""CurseForge game/category mod listing 등록.

URL 패턴 (두 form):
  - https://www.curseforge.com/<game>                   (게임 hub — shelf 섹션의 mod tiles)
  - https://www.curseforge.com/<game>/<category>        (category 직접 listing — search?class=<category>)

CF challenge 있음 — playwright_html + stealth (patchright 자체 stealth) 사용.
playwright_stealth lib race 회피 위해 disable_stealth: true.

Single-mod URL (`/<game>/<category>/<slug>`) 또는 download URL 은 fall through (None).
"""
from __future__ import annotations

import re
from typing import Optional


NAME = "curseforge"

# pattern 1: game/category (예: /minecraft/mc-mods, /wow/addons)
_PATTERN_CATEGORY = re.compile(
    r"//(?:www\.)?curseforge\.com/([a-z][\w-]*)/([a-z][\w-]*)/?$",
    re.I,
)
# pattern 2: game root (예: /minecraft, /skyrim)
_PATTERN_GAME = re.compile(
    r"//(?:www\.)?curseforge\.com/([a-z][\w-]*)/?$",
    re.I,
)
# 비-board: 단일 mod 페이지, download, install, api
_RESERVED_SUB = {"download", "install", "search", "members", "api", "linkout"}


def _shared_cfg(extra: dict) -> dict:
    base = {
        "version": 1,
        "site": "curseforge.com",
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
            "Referer": "https://www.curseforge.com/",
        },
        "timeout": 15,
        "nav_timeout_ms": 12000,
        "idle_timeout_ms": 3000,
        "quiet_ms": 250,
    }
    base.update(extra)
    return base


def _build_category(m: "re.Match", url: str) -> Optional[dict]:
    game, category = m.group(1).lower(), m.group(2).lower()
    if category in _RESERVED_SUB:
        return None
    src = f"https://www.curseforge.com/{game}/search?class={category}&sortBy=newest&page=1&pageSize=20"
    cfg = _shared_cfg({
        "board": category,
        "_slug_board": f"{game}_{category}",
        "_source_url": src,
        "_note": (f"CurseForge {game}/{category} mod listing — search API URL "
                  "newest 정렬, project-card grid. playwright_html + disable_stealth."),
        "list": {
            "url_template": f"https://www.curseforge.com/{game}/search?class={{board}}&sortBy=newest&page={{page}}&pageSize=20",
            "pagination": {"kind": "query_param", "page_param": "page"},
            "wait_selector": "div.results-container > div.project-card",
            "row_selector": "div.results-container > div.project-card",
            "row_required_selector": "a.download-cta, a.project-card-link",
            "include_notices": True,
            "fields": {
                "post_id": [{
                    "from": "attr",
                    "selector": "a.download-cta",
                    "attr": "href",
                    "transform": [["regex_extract", "/download/(\\d+)"]],
                }, {
                    "from": "attr",
                    "selector": "a[href*='/install/']",
                    "attr": "href",
                    "transform": [["regex_extract", "/install/(\\d+)"]],
                }],
                "title": [{
                    "from": "css",
                    "selector": "a.project-card-link, h3, a[href*='/" + game + "/" + category + "/']",
                    "text": True,
                    "transform": [["collapse_ws"]],
                }],
                "url": [{
                    "from": "attr",
                    "selector": "a.project-card-link, a[href*='/" + game + "/" + category + "/']",
                    "attr": "href",
                    "transform": [["urljoin", "https://www.curseforge.com"]],
                }],
                "summary": [{
                    "from": "css",
                    "selector": "p.description, .project-description",
                    "text": True,
                    "transform": [["collapse_ws"]],
                }],
            },
        },
        "article": {
            "fetch_kind": "html",
            "wait_selector": "main",
            "content": [
                {"from": "css", "selector": "div.project-description, main", "html": True},
            ],
            "enrich": {
                "title": [{"from": "css", "selector": "h1, h2", "text": True, "transform": [["collapse_ws"]]}],
            },
        },
    })
    return cfg


def _build_game(m: "re.Match", url: str) -> Optional[dict]:
    game = m.group(1).lower()
    if game in _RESERVED_SUB:
        return None
    src = f"https://www.curseforge.com/{game}"
    cfg = _shared_cfg({
        "board": game,
        "_slug_board": game,
        "_source_url": src,
        "_note": (f"CurseForge {game} hub — shelf 섹션의 mod tiles 폴링. "
                  "playwright_html + disable_stealth. category 별 sub-URL 도 가능 (`/<game>/<category>`)."),
        "list": {
            "url_template": f"https://www.curseforge.com/{{board}}",
            "pagination": {"kind": "none"},
            "wait_selector": "section.shelf",
            "row_selector": "section.shelf .desktop-only ul.tiles-list > li.project-tile",
            "row_required_selector": "a[href*='/install/'], a[href*='/download/'], a.btn-cta",
            "include_notices": True,
            "fields": {
                "post_id": [{
                    "from": "attr",
                    "selector": "a.btn-cta[href*='/install/'], a[href*='/install/']",
                    "attr": "href",
                    "transform": [["regex_extract", "/install/(\\d+)"]],
                }, {
                    "from": "attr",
                    "selector": "a.download-cta[href*='/download/'], a[href*='/download/']",
                    "attr": "href",
                    "transform": [["regex_extract", "/download/(\\d+)"]],
                }],
                "title": [{
                    "from": "css",
                    "selector": "h3, .project-name, a.project-link",
                    "text": True,
                    "transform": [["collapse_ws"]],
                }],
                "url": [{
                    "from": "attr",
                    "selector": "a.project-link, a[href*='/" + game + "/']",
                    "attr": "href",
                    "transform": [["urljoin", "https://www.curseforge.com"]],
                }],
                "summary": [{
                    "from": "css",
                    "selector": "p.description, .project-description",
                    "text": True,
                    "transform": [["collapse_ws"]],
                }],
            },
        },
        "article": {
            "fetch_kind": "html",
            "wait_selector": "main",
            "content": [
                {"from": "css", "selector": "div.project-description, main", "html": True},
            ],
            "enrich": {
                "title": [{"from": "css", "selector": "h1, h2", "text": True, "transform": [["collapse_ws"]]}],
            },
        },
    })
    return cfg


# pattern 우선순위: category (2-segment) 가 game root (1-segment) 보다 먼저 시도되도록 list 순서 박음.
# re module 은 첫 번째 매칭 PATTERNS 사용 (engine/recognizers/__init__.py).
PATTERNS = [
    (_PATTERN_CATEGORY, _build_category),
    (_PATTERN_GAME, _build_game),
]
