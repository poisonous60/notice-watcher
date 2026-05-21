"""클리앙 게시판 → httpx_html.

URL 폼: https://www.clien.net/service/board/<board>

승급 출처: 자동생성 config 4건(lecture/park/news/use). 게시판별 selector 편차가 있어
현재 검증된 네 게시판만 명시적으로 인식한다.
"""
from __future__ import annotations

import re
from typing import Optional

from ._common import UA, qs

NAME = "clien"

_RE = re.compile(r"//(?:www\.)?clien\.net/service/board/(lecture|park|news|use)(?:[/?#]|$)", re.I)
_BOARDS_WITH_FILTER_QUERY = {"news", "use"}


def _view_url(board: str) -> str:
    base = f"https://www.clien.net/service/board/{board}"
    if board in _BOARDS_WITH_FILTER_QUERY:
        return base + "?od=T31&category=0&groupCd="
    return base


def _site(board: str) -> str:
    return "www.clien.net" if board == "lecture" else "clien.net"


def _build(m: "re.Match", url: str) -> Optional[dict]:
    board = m.group(1).lower()
    qs(url)  # keep tracking-query normalization helper in the recognizer path.

    cfg = {
        "version": 1,
        "site": _site(board),
        "board": board,
        "strategy": "httpx_html",
        "_slug_board": board,
        "headers": _headers(board),
        "timeout": 15,
        "list": _list(board),
        "article": _article(board),
        "_source_url": _view_url(board),
        "_note": (
            f"Clien {board} 게시판 — known-platform 자동 인식. /service/board/{board} path 에서 "
            "board 를 추출하고, 검증된 HTML selector skeleton 을 게시판별로 적용."
        ),
    }
    return cfg


def _headers(board: str) -> dict:
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": f"https://www.clien.net/service/board/{board}",
    }
    if board == "news":
        headers["Accept"] = (
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,"
            "image/apng,*/*;q=0.8,application/signed-exchanged;v=b3;q=0.7"
        )
        headers["Accept-Language"] = "ko-KR"
    if board in {"lecture", "news", "use"}:
        headers["Upgrade-Insecure-Requests"] = "1"
    return headers


def _list(board: str) -> dict:
    if board == "lecture":
        return {
            "url_template": "https://www.clien.net/service/board/{board}",
            "pagination": {"kind": "query_param", "page_param": "po"},
            "include_notices": True,
            "row_selector": "div.list_content > div.list_item.symph_row",
            "row_required_selector": "a.list_subject[href*='/service/board/lecture/']",
            "exclude_selector": "div.list_item.blocked",
            "fields": {
                "post_id": [
                    {"from": "attr", "selector": ":self", "attr": "data-board-sn"},
                    {"from": "attr", "selector": "a.list_subject", "attr": "href",
                     "transform": [["regex_extract", "/service/board/lecture/(\\d+)"]]},
                ],
                "title": _title_fields("span.subject_fixed", "a.list_subject"),
                "url": _url_field(),
                "published_at": [
                    {"from": "css", "selector": "span.timestamp", "text": True,
                     "transform": [["iso8601", ["%Y-%m-%d %H:%M:%S"], "+09:00"]]},
                    {"from": "css", "selector": "div.list_time .time.popover", "text": True,
                     "transform": [["collapse_ws"], ["iso8601", ["%m-%d %H:%M:%S"], "+09:00"]]},
                ],
                "author": _author_fields(collapse_title=False),
                "category": _category_title_fields(),
                "summary": [{"from": "css", "selector": "a.list_subject span.subject_fixed", "text": True,
                             "transform": [["collapse_ws"]]}],
            },
        }
    if board == "park":
        return {
            "url_template": "https://www.clien.net/service/board/{board}",
            "pagination": {"kind": "query_param", "page_param": "po"},
            "row_selector": "div.list_content > div.list_item.symph_row",
            "row_required_selector": "a.list_subject[href*='/service/board/park/']",
            "exclude_selector": "div.list_item.hongbo",
            "include_notices": True,
            "fields": {
                "post_id": [{"from": "attr", "selector": ":self", "attr": "data-board-sn"}],
                "title": _title_fields("span.subject_fixed", "a.list_subject"),
                "url": _url_field(),
                "published_at": [{"from": "css", "selector": "span.timestamp", "text": True,
                                  "transform": [["iso8601", ["%Y-%m-%d %H:%M:%S"], "+09:00"]]}],
                "author": _author_fields(collapse_title=True),
                "summary": [{"from": "css", "selector": "div.list_title span.subject_fixed", "text": True,
                             "transform": [["collapse_ws"]]}],
            },
        }
    if board == "news":
        return {
            "url_template": "https://www.clien.net/service/board/news?od=T31&category=0&groupCd=",
            "pagination": {
                "kind": "offset",
                "offset_param": "po",
                "page_unit": 1,
                "extra_params_when_paged": {"od": "T31", "category": "0", "groupCd": ""},
            },
            "row_selector": "div.list_content > div.list_item.notice, div.list_content > div.list_item.symph_row",
            "row_required_selector": "a.list_subject",
            "include_notices": True,
            "fields": {
                "post_id": [{"from": "attr", "selector": "a.list_subject", "attr": "href",
                             "transform": [["regex_extract", "/service/board/news/(\\d+)"]]}],
                "title": _title_fields("a.list_subject > span.subject_fixed", "a.list_subject"),
                "url": _url_field(),
                "published_at": [
                    {"from": "css", "selector": "span.timestamp", "text": True,
                     "match": "^\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}$",
                     "transform": [["iso8601", ["%Y-%m-%d %H:%M:%S"], "+09:00"]]},
                    {"from": "css", "selector": "div.list_time span.time.popover", "text": True,
                     "transform": [["collapse_ws"], ["regex_extract", "(\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2})"],
                                   ["iso8601", ["%Y-%m-%d %H:%M:%S"], "+09:00"]]},
                ],
                "author": _author_fields(collapse_title=True),
            },
        }
    if board == "use":
        return {
            "url_template": "https://www.clien.net/service/board/use?od=T31&category=0&groupCd=",
            "pagination": {"kind": "query_param", "page_param": "po"},
            "row_selector": "div.list_content > div.list_item.symph_row[data-role='list-row']",
            "row_required_selector": "a.list_subject",
            "include_notices": False,
            "fields": {
                "post_id": [{"from": "attr", "selector": "a.list_subject", "attr": "href",
                             "transform": [["regex_extract", "/service/board/use/(\\d+)"]]}],
                "title": [{"from": "css", "selector": "span.subject_fixed", "text": True,
                           "transform": [["collapse_ws"]]}],
                "url": _url_field(),
                "category": [{"from": "css", "selector": "span.category.fixed", "text": True,
                              "transform": [["collapse_ws"], ["strip"]]}],
                "author": [{"from": "attr", "selector": "div.list_author .nickname span[title]",
                            "attr": "title", "transform": [["collapse_ws"]]}],
                "published_at": [{"from": "css", "selector": "span.timestamp", "text": True,
                                  "transform": [["iso8601", ["%Y-%m-%d %H:%M:%S"], "+09:00"]]}],
            },
        }
    raise AssertionError(f"unsupported clien board: {board}")


def _article(board: str) -> dict:
    if board == "lecture":
        return {
            "url_template": "https://www.clien.net/service/board/{board}/{post_id}?od=T31&po=0&category=0&groupCd=",
            "fetch_kind": "html",
            "content": [
                {"from": "css", "selector": "div.post_content div.post_article", "html": True},
                {"from": "css", "selector": "div.post_content article", "html": True},
                {"from": "css", "selector": "div.content_view div.post_view", "html": True},
            ],
            "enrich": {
                "title": [
                    {"from": "css", "selector": "h3.post_subject span:last-child", "text": True,
                     "transform": [["collapse_ws"]]},
                    {"from": "css", "selector": "input#subject", "attr": "value"},
                ],
                "published_at": [_article_date("div.post_author span.view_count.date", with_regex=True)],
                "author": [
                    {"from": "css", "selector": "div.post_info div.nickname span[title]", "attr": "title"},
                    {"from": "css", "selector": "input#writer", "attr": "value"},
                ],
            },
        }
    if board == "park":
        return {
            "fetch_kind": "html",
            "content": [
                {"from": "css", "selector": "div.post_view div.post_article", "html": True},
                {"from": "css", "selector": "div.post_view article", "html": True},
            ],
            "enrich": {
                "title": [{"from": "css", "selector": "h3.post_subject span", "text": True,
                           "transform": [["collapse_ws"]]}],
                "published_at": [_article_date("div.post_author span.view_count.date", with_regex=False)],
            },
        }
    if board == "news":
        return {
            "fetch_kind": "html",
            "content": [
                {"from": "css", "selector": "div.post_view div.post_content div.post_article", "html": True},
                {"from": "css", "selector": "div.post_view article div.post_article", "html": True},
                {"from": "css", "selector": "div.post_view .post_content", "html": True},
            ],
            "enrich": {
                "title": [
                    {"from": "css", "selector": "div.post_title h3.post_subject > span", "text": True,
                     "transform": [["collapse_ws"]]},
                    {"from": "css", "selector": "input#subject", "attr": "value", "transform": [["collapse_ws"]]},
                ],
                "published_at": [_article_date("div.post_author span.view_count.date", with_regex=True)],
                "author": [
                    {"from": "css", "selector": "div.post_info span.nickname span[title]", "attr": "title",
                     "transform": [["collapse_ws"]]},
                    {"from": "css", "selector": "input#writer", "attr": "value", "transform": [["collapse_ws"]]},
                ],
            },
        }
    if board == "use":
        return {
            "fetch_kind": "html",
            "content": [
                {"from": "css", "selector": "div.post_view div.post_content > article > div.post_article", "html": True},
                {"from": "css", "selector": "div.post_view div.post_content article", "html": True},
            ],
            "enrich": {
                "title": [{"from": "css", "selector": "div.post_title h3.post_subject > span:last-child", "text": True,
                           "transform": [["collapse_ws"]]}],
                "author": [{"from": "attr", "selector": "div.post_info .nickname span[title]",
                            "attr": "title", "transform": [["collapse_ws"]]}],
                "published_at": [_article_date("div.post_author .view_count.date", with_regex=False, collapse=True)],
            },
        }
    raise AssertionError(f"unsupported clien board: {board}")


def _title_fields(primary_selector: str, fallback_selector: str) -> list[dict]:
    return [
        {"from": "css", "selector": primary_selector, "text": True, "transform": [["collapse_ws"]]},
        {"from": "css", "selector": fallback_selector, "text": True, "transform": [["collapse_ws"]]},
    ]


def _url_field() -> list[dict]:
    return [{"from": "attr", "selector": "a.list_subject", "attr": "href",
             "transform": [["urljoin", "https://www.clien.net"]]}]


def _author_fields(*, collapse_title: bool) -> list[dict]:
    first = {"from": "css", "selector": "div.list_author span.nickname span[title]", "attr": "title"}
    if collapse_title:
        first["transform"] = [["collapse_ws"]]
    return [
        first,
        {"from": "css", "selector": "div.list_author span.nickname", "text": True, "transform": [["collapse_ws"]]},
    ]


def _category_title_fields() -> list[dict]:
    return [
        {"from": "css", "selector": "span.category.fixed", "attr": "title"},
        {"from": "css", "selector": "span.category.fixed", "text": True, "transform": [["collapse_ws"]]},
    ]


def _article_date(selector: str, *, with_regex: bool, collapse: bool = False) -> dict:
    transform = []
    if collapse or with_regex:
        transform.append(["collapse_ws"])
    if with_regex:
        transform.append(["regex_extract", "(\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2})"])
    transform.append(["iso8601", ["%Y-%m-%d %H:%M:%S"], "+09:00"])
    return {"from": "css", "selector": selector, "text": True, "transform": transform}


PATTERNS = [
    (_RE, _build),
]
