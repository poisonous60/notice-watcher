"""Ruliweb board URLs -> httpx_html configs.

URL forms promoted from four generated configs:
  - https://bbs.ruliweb.com/mobile/board/<board>/rss
  - https://bbs.ruliweb.com/news/board/<board>/rss
  - https://bbs.ruliweb.com/pc/board/<board>/rss
  - https://bbs.ruliweb.com/ps/board/<board>

The host is shared, but RSS sections and the PS HTML board use different
selectors, so the builder branches by section instead of pretending the cluster
has one uniform selector skeleton.
"""
from __future__ import annotations

import re
from typing import Optional

from ._common import UA

NAME = "ruliweb"

# Board roots only. Article pages add /read/<id> and must not match.
_RE = re.compile(
    r"//bbs\.ruliweb\.com/(mobile|news|pc|ps)/board/(\d+)(/rss)?(?:[?#]|/?$)",
    re.I,
)


def _rss_date_field() -> dict:
    return {
        "from": "css",
        "selector": "pubDate",
        "text": True,
        "transform": [["iso8601", ["%a, %d %b %Y %H:%M:%S %z"]]],
    }


def _rss_common_fields(html_unescape: bool = False) -> dict:
    text_transforms = [["collapse_ws"]]
    strip_transforms = [["strip"]]
    if html_unescape:
        text_transforms.append(["html_unescape"])
        strip_transforms.append(["html_unescape"])
    return {
        "post_id": [
            {
                "from": "css",
                "selector": "link",
                "text": True,
                "transform": [["regex_extract", r"/read/(\d+)$"]],
            }
        ],
        "title": [
            {
                "from": "css",
                "selector": "title",
                "text": True,
                "transform": text_transforms,
            }
        ],
        "url": [
            {
                "from": "css",
                "selector": "link",
                "text": True,
                "transform": strip_transforms,
            }
        ],
        "published_at": [_rss_date_field()],
        "author": [
            {
                "from": "css",
                "selector": "author",
                "text": True,
                "transform": text_transforms,
            }
        ],
        "category": [
            {
                "from": "css",
                "selector": "category",
                "text": True,
                "transform": text_transforms,
            }
        ],
    }


def _headers(referer: str | None = None, accept_language: str = "ko-KR,ko;q=0.9") -> dict:
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": accept_language,
        "Upgrade-Insecure-Requests": "1",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def _build_mobile(board: str, source_url: str) -> dict:
    return {
        "version": 1,
        "site": "bbs.ruliweb.com",
        "board": board,
        "strategy": "httpx_html",
        "_slug_board": f"mobile_{board}",
        "headers": _headers(source_url),
        "timeout": 15,
        "list": {
            "url_template": "https://bbs.ruliweb.com/mobile/board/{board}/rss",
            "pagination": {"kind": "none"},
            "row_selector": "item",
            "fields": {
                **_rss_common_fields(),
                "post_id": [
                    {
                        "from": "css",
                        "selector": "link",
                        "text": True,
                        "match": r"^https?://.+/read/\d+$",
                        "transform": [["regex_extract", r"/read/(\d+)$"]],
                    }
                ],
                "url": [
                    {
                        "from": "css",
                        "selector": "link",
                        "text": True,
                        "transform": [["strip"], ["urljoin", "https://bbs.ruliweb.com"]],
                    }
                ],
            },
        },
        "article": {
            "url_template": "https://bbs.ruliweb.com/mobile/board/{board}/read/{post_id}",
            "fetch_kind": "html",
            "content": [
                {"from": "css", "selector": "div.article_content", "html": True},
                {"from": "css", "selector": "div.view_content", "html": True},
                {"from": "css", "selector": "div.board_view_contents", "html": True},
                {"from": "css", "selector": "div#content", "html": True},
            ],
            "enrich": {
                "title": [
                    {"from": "css", "selector": "h3.title", "text": True, "transform": [["collapse_ws"]]},
                    {"from": "css", "selector": "title", "text": True, "transform": [["collapse_ws"]]},
                ],
                "published_at": [
                    {"from": "css", "selector": "time", "attr": "datetime"},
                    _rss_date_field(),
                ],
            },
        },
        "_source_url": source_url,
        "_note": f"Ruliweb mobile RSS board={board} 자동 인식. /mobile/board/{{board}}/rss 목록과 /read/{{post_id}} 본문.",
    }


def _build_news(board: str, source_url: str) -> dict:
    fields = _rss_common_fields()
    fields["url"] = [{"from": "css", "selector": "link", "text": True}]
    fields["summary"] = [
        {"from": "css", "selector": "description", "text": True, "transform": [["collapse_ws"]]}
    ]
    fields["cover_image"] = [
        {"from": "css", "selector": "description", "text": True, "transform": [["regex_extract", r'src="([^"]+)"']]}
    ]
    return {
        "version": 1,
        "site": f"host_bbs-ruliweb-com_news_b596932d" if board == "1001" else "bbs.ruliweb.com",
        "board": board,
        "strategy": "httpx_html",
        "_slug_board": f"news_{board}",
        "headers": _headers(None, "ko-KR,ko;q=0.9,en;q=0.8"),
        "timeout": 15,
        "list": {
            "url_template": f"https://bbs.ruliweb.com/news/board/{board}/rss",
            "pagination": {"kind": "none"},
            "row_selector": "channel > item",
            "include_notices": True,
            "fields": fields,
        },
        "article": {
            "fetch_kind": "html",
            "content": [
                {"from": "css", "selector": "div.view_content", "html": True},
                {"from": "css", "selector": "div.article_content", "html": True},
                {"from": "css", "selector": "div.news_view_contents", "html": True},
                {"from": "css", "selector": "div.view_content_wrap", "html": True},
            ],
            "enrich": {
                "title": [
                    {"from": "css", "selector": "h2.view_title", "text": True, "transform": [["collapse_ws"]]}
                ],
                "published_at": [
                    {
                        "from": "css",
                        "selector": "div.view_info time",
                        "text": True,
                        "transform": [["iso8601", ["%Y.%m.%d %H:%M"], "+09:00"]],
                    }
                ],
            },
        },
        "_source_url": source_url,
        "_note": f"Ruliweb news RSS board={board} 자동 인식. channel>item RSS 목록, news view_content 계열 본문.",
    }


def _build_pc(board: str, source_url: str) -> dict:
    return {
        "version": 1,
        "site": "bbs.ruliweb.com",
        "board": f"pc/board/{board}",
        "strategy": "httpx_html",
        "_slug_board": f"pc_{board}",
        "headers": _headers(None, "ko-KR,ko;q=0.9,en;q=0.8"),
        "timeout": 15,
        "list": {
            "url_template": f"https://bbs.ruliweb.com/pc/board/{board}/rss",
            "pagination": {"kind": "none"},
            "row_selector": "item",
            "fields": {
                **_rss_common_fields(html_unescape=True),
                "summary": [
                    {
                        "from": "css",
                        "selector": "description",
                        "text": True,
                        "transform": [["collapse_ws"], ["html_unescape"]],
                    }
                ],
            },
        },
        "article": {
            "fetch_kind": "html",
            "content": [
                {"from": "css", "selector": "div.view_content", "html": True},
                {"from": "css", "selector": "div.article_view", "html": True},
                {"from": "css", "selector": "div.article-content", "html": True},
                {"from": "css", "selector": "article", "html": True},
            ],
            "enrich": {
                "title": [
                    {
                        "from": "css",
                        "selector": "h3.title",
                        "text": True,
                        "transform": [["collapse_ws"], ["html_unescape"]],
                    },
                    {
                        "from": "css",
                        "selector": "title",
                        "text": True,
                        "transform": [["collapse_ws"], ["html_unescape"]],
                    },
                ],
                "published_at": [{"from": "css", "selector": "time, .date, .regdate", "text": True}],
            },
        },
        "_source_url": source_url,
        "_note": f"Ruliweb PC RSS board={board} 자동 인식. /pc/board/{{board}}/rss 목록, HTML unescape 적용.",
    }


def _build_ps(board: str, source_url: str) -> dict:
    return {
        "version": 1,
        "site": "bbs.ruliweb.com",
        "board": board,
        "strategy": "httpx_html",
        "_slug_board": f"ps_{board}",
        "headers": _headers(source_url),
        "timeout": 15,
        "list": {
            "url_template": "https://bbs.ruliweb.com/ps/board/{board}",
            "pagination": {"kind": "query_param", "page_param": "page"},
            "row_selector": "table.board_list_table > tbody > tr, div.board_list_table > table > tbody > tr, .board_list_table tbody tr",
            "row_required_selector": "a[href*='/read/']",
            "include_notices": True,
            "fields": {
                "post_id": [
                    {
                        "from": "attr",
                        "selector": "a[href*='/read/']",
                        "attr": "href",
                        "transform": [["regex_extract", r"/read/(\d+)"]],
                    }
                ],
                "title": [
                    {
                        "from": "css",
                        "selector": "a[href*='/read/']",
                        "text": True,
                        "transform": [["collapse_ws"]],
                    }
                ],
                "url": [
                    {
                        "from": "attr",
                        "selector": "a[href*='/read/']",
                        "attr": "href",
                        "transform": [["urljoin", "https://bbs.ruliweb.com"]],
                    }
                ],
                "published_at": [
                    {
                        "from": "css",
                        "selector": "time, .time, .date, td",
                        "pick": "first_matching",
                        "match": r"^\d{4}-\d{2}-\d{2}|^\d{4}\.\d{2}\.\d{2}|^\d{2}:\d{2}$",
                        "text": True,
                        "transform": [
                            ["collapse_ws"],
                            ["iso8601", ["%Y-%m-%d %H:%M", "%Y.%m.%d %H:%M", "%Y-%m-%d", "%Y.%m.%d"], "+09:00"],
                        ],
                    },
                    {
                        "from": "css",
                        "selector": "a[href*='/read/'] + span, a[href*='/read/'] ~ span",
                        "text": True,
                        "transform": [["collapse_ws"]],
                    },
                ],
                "author": [
                    {
                        "from": "css",
                        "selector": "a[href*='/read/'] ~ span, .nick, .writer, .author",
                        "pick": "first_matching",
                        "match": r"^.+$",
                        "text": True,
                        "transform": [["collapse_ws"]],
                    }
                ],
                "category": [
                    {
                        "from": "css",
                        "selector": "a[href*='/read/'] ~ span, .subject, .cate, .category",
                        "pick": "first_matching",
                        "match": r"^.+$",
                        "text": True,
                        "transform": [["collapse_ws"]],
                    }
                ],
            },
        },
        "article": {
            "fetch_kind": "html",
            "content": [
                {"from": "css", "selector": "div.view_content", "html": True},
                {"from": "css", "selector": "div#view_content", "html": True},
                {"from": "css", "selector": "div.article_content", "html": True},
                {"from": "css", "selector": "div.fr-view", "html": True},
            ],
        },
        "_source_url": source_url,
        "_note": f"Ruliweb PS board={board} 자동 인식. HTML board_list_table 목록, page 쿼리 페이징.",
    }


def _build(m: "re.Match", url: str) -> Optional[dict]:
    section = m.group(1).lower()
    board = m.group(2)
    has_rss = bool(m.group(3))
    source_url = f"https://bbs.ruliweb.com/{section}/board/{board}" + ("/rss" if has_rss else "")

    if section in {"mobile", "news", "pc"} and not has_rss:
        return None
    if section == "ps" and has_rss:
        return None
    if section == "mobile":
        return _build_mobile(board, source_url)
    if section == "news":
        return _build_news(board, source_url)
    if section == "pc":
        return _build_pc(board, source_url)
    if section == "ps":
        return _build_ps(board, source_url)
    return None


PATTERNS = [
    (_RE, _build),
]
