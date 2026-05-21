"""Ppomppu zboard 게시판 → httpx_html.

URL 폼: https://www.ppomppu.co.kr/zboard/zboard.php?id=<board>[&divpage=<n>]
  - board = query `id` 값.
  - zboard.php 목록 페이지만 인식한다. view.php 단일 글, root, 다른 zboard 경로는 제외.

승급 출처: N100 snapshot 의 자동/수동 config 3건(ppomppu/computer/phone)이 같은
`#revolution_main_table tr.baseList` 기반 DOM 을 공유해 recognizer-extension 으로 묶음.
일부 header/selector 차이는 기존 config 재현을 위해 board 별로 보존한다.
"""
from __future__ import annotations

import re
from typing import Optional

from ._common import UA, qs

NAME = "ppomppu"

_RE = re.compile(
    r"//(?:www\.)?ppomppu\.co\.kr/zboard/zboard\.php\?[^#]*\bid=([A-Za-z0-9_%-]+)",
    re.I,
)


def _standard_fields() -> dict:
    return {
        "post_id": [
            {
                "from": "attr",
                "selector": "a.baseList-title",
                "attr": "href",
                "transform": [["regex_extract", "[?&]no=(\\d+)"]],
            }
        ],
        "title": [
            {
                "from": "css",
                "selector": "a.baseList-title",
                "text": True,
                "transform": [["collapse_ws"]],
            }
        ],
        "url": [
            {
                "from": "attr",
                "selector": "a.baseList-title",
                "attr": "href",
                "transform": [["urljoin", "https://www.ppomppu.co.kr/zboard/"]],
            }
        ],
        "published_at": [
            {
                "from": "css",
                "selector": "td.baseList-time",
                "attr": "title",
                "match": "^\\d{2}\\.\\d{2}\\.\\d{2} \\d{2}:\\d{2}:\\d{2}$",
                "transform": [["iso8601", ["%y.%m.%d %H:%M:%S"], "+09:00"]],
            },
            {
                "from": "css",
                "selector": "td.baseList-time",
                "text": True,
                "match": "^\\d{2}/\\d{2}/\\d{2}$",
                "transform": [["iso8601", ["%y/%m/%d"], "+09:00"]],
            },
        ],
        "author": [
            {
                "from": "css",
                "selector": "a.baseList-name span.baseList-name",
                "text": True,
                "transform": [["collapse_ws"]],
            }
        ],
        "summary": [
            {
                "from": "css",
                "selector": "a.baseList-title",
                "text": True,
                "transform": [["collapse_ws"]],
            }
        ],
    }


def _phone_fields() -> dict:
    fields = _standard_fields()
    fields["post_id"][0]["transform"] = [
        ["urljoin", "https://www.ppomppu.co.kr/zboard/"],
        ["regex_extract", "[?&]no=(\\d+)"],
    ]
    fields["published_at"] = [
        {
            "from": "attr",
            "selector": "td[title]",
            "attr": "title",
            "match": "^\\d{2}\\.\\d{2}\\.\\d{2} \\d{2}:\\d{2}:\\d{2}$",
            "transform": [["iso8601", ["%y.%m.%d %H:%M:%S"], "+09:00"]],
        },
        {
            "from": "css",
            "selector": "time.baseList-time",
            "text": True,
            "match": "^\\d{2}/\\d{2}/\\d{2}$",
            "transform": [["iso8601", ["%y/%m/%d"], "+09:00"]],
        },
        {
            "from": "css",
            "selector": "time.baseList-time",
            "text": True,
            "match": "^\\d{2}:\\d{2}:\\d{2}$",
        },
    ]
    fields["author"] = [
        {
            "from": "css",
            "selector": "a.baseList-name, .list_name .baseList-name",
            "text": True,
            "transform": [["collapse_ws"]],
        }
    ]
    fields.pop("summary")
    fields["category"] = [
        {
            "from": "css",
            "selector": "#topNotice span#notice-icon",
            "text": True,
            "transform": [["collapse_ws"]],
        },
        {
            "from": "css",
            "selector": "#topNotice span#alert-icon",
            "text": True,
            "transform": [["collapse_ws"]],
        },
        {
            "from": "css",
            "selector": "#topNotice span#ad-icon",
            "text": True,
            "transform": [["collapse_ws"]],
        },
    ]
    return fields


def _article(phone: bool = False) -> dict:
    article = {
        "fetch_kind": "html",
        "content": [
            {"from": "css", "selector": "div.JS_ContentMain td.board-contents", "html": True},
            {"from": "css", "selector": "td.board-contents", "html": True},
        ],
        "enrich": {
            "title": [
                {
                    "from": "css",
                    "selector": "#topTitle h1",
                    "text": True,
                    "transform": [["collapse_ws"]],
                }
            ],
            "published_at": [
                {
                    "from": "css",
                    "selector": "div.topTitle-box > ul.topTitle-mainbox > li",
                    "pick": "first_matching",
                    "match": "^등록일\\s+\\d{4}-\\d{2}-\\d{2}\\s+\\d{2}:\\d{2}$",
                    "text": True,
                    "transform": [
                        ["regex_extract", "등록일\\s+(\\d{4}-\\d{2}-\\d{2}\\s+\\d{2}:\\d{2})"],
                        ["replace", " ", "T"],
                        ["append", ":00+09:00"],
                    ],
                }
            ],
        },
    }
    if not phone:
        return article
    article["url_template"] = "https://www.ppomppu.co.kr/zboard/view.php?id={board}&no={post_id}"
    article["content"] = [
        {"from": "css", "selector": "td.board-contents", "html": True},
        {"from": "css", "selector": "div.JS_ContentMain td.board-contents", "html": True},
        {"from": "css", "selector": "div.JS_ContentMain .board-contents", "html": True},
    ]
    article["enrich"]["published_at"][0]["selector"] = "#topTitle li"
    return article


def _build(m: "re.Match", url: str) -> Optional[dict]:
    query = qs(url)
    board = query.get("id") or m.group(1)
    if not board:
        return None
    divpage = query.get("divpage")
    source_url = f"https://www.ppomppu.co.kr/zboard/zboard.php?id={board}"
    if divpage:
        source_url += f"&divpage={divpage}"
    phone = board == "phone"

    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        "Referer": source_url,
    }
    if phone:
        headers = {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Upgrade-Insecure-Requests": "1",
            "Sec-CH-UA": "\"Chromium\";v=\"147\", \"Not.A/Brand\";v=\"8\"",
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": "\"Windows\"",
            "Referer": source_url,
        }

    list_cfg = {
        "url_template": "https://www.ppomppu.co.kr/zboard/zboard.php?id={board}",
        "pagination": {"kind": "query_param", "page_param": "page", "size_param": "page_num"},
        "page_size_max": 30,
        "row_selector": "#revolution_main_table tr.baseList",
        "include_notices": True,
        "fields": _phone_fields() if phone else _standard_fields(),
    }
    if divpage:
        list_cfg["url_template"] += f"&divpage={divpage}"
    if phone:
        list_cfg["pagination"] = {"kind": "query_param", "page_param": "page"}
        list_cfg.pop("page_size_max")
        list_cfg["row_required_selector"] = "a.baseList-title"

    return {
        "version": 1,
        "site": "ppomppu.co.kr" if phone else "www.ppomppu.co.kr",
        "board": board,
        "strategy": "httpx_html",
        "_slug_board": f"zboard_{board}",
        "headers": headers,
        "timeout": 15,
        "list": list_cfg,
        "article": _article(phone),
        "_source_url": source_url,
        "_note": (
            f"Ppomppu zboard 게시판(id={board}) — known-platform 자동 인식. "
            "목록 #revolution_main_table tr.baseList, 제목/URL a.baseList-title, "
            "본문 td.board-contents. board 는 query id 에서 추출."
        ),
    }


PATTERNS = [
    (_RE, _build),
]
