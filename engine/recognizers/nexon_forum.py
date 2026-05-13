"""넥슨 포럼 → httpx_json (공개 API: /api/v1/board/{board}/threads, /api/v1/thread/{id})."""
from __future__ import annotations

import re
from typing import Optional

from ._common import UA, qs

NAME = "nexon-forum"


def _build(m: "re.Match", url: str) -> Optional[dict]:
    game = m.group(1)
    board = qs(url).get("board")
    if not (board and str(board).isdigit()):
        return None
    view_url = f"https://forum.nexon.com/{game}/board_list?board={board}"
    return {
        "version": 1, "site": "forum.nexon.com", "board": str(board), "strategy": "httpx_json",
        "_source_url": view_url,
        "_note": (f"넥슨 포럼({game}) — known-platform 자동 인식. 목록=/api/v1/board/{{board}}/threads?alias={game}, "
                  f"본문=/api/v1/thread/{{threadId}}?alias={game}. createDate=unix epoch(초), title/summary 는 HTML 이스케이프됨."),
        "headers": {
            "User-Agent": UA, "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "ko-KR,ko;q=0.9", "X-Requested-With": "XMLHttpRequest", "Referer": view_url,
        },
        "timeout": 15.0,
        "list": {
            "url_template": f"https://forum.nexon.com/api/v1/board/{{board}}/threads?alias={game}&paginationType=PAGING&pageSize=30&blockSize=5&hideType=WEB",
            "pagination": {"kind": "query_param", "page_param": "pageNo"},
            "list_path": ["threads"],
            "fields": {
                "post_id": [{"from": "json", "path": ["threadId"]}],
                "title": [{"from": "json", "path": ["title"], "transform": [["html_unescape"], ["collapse_ws"]]}],
                "url": [{"from": "template", "value": f"https://forum.nexon.com/{game}/board_view?board={{board}}&thread={{post_id}}"}],
                "published_at": [{"from": "json", "path": ["createDate"], "transform": [["unixtime_to_iso", "+09:00", "s"]]}],
                "author": [{"from": "json", "path": ["user", "nickname"]}],
                "summary": [{"from": "json", "path": ["summary"], "transform": [["html_unescape"], ["collapse_ws"]]}],
                "cover_image": [{"from": "json", "path": ["thumbnailImageUrl"]}],
            },
        },
        "article": {
            "url_template": f"https://forum.nexon.com/api/v1/thread/{{post_id}}?alias={game}",
            "fetch_kind": "json", "content": [{"from": "json", "path": ["content"]}], "re_extract": True,
        },
    }


PATTERNS = [
    (re.compile(r"//forum\.nexon\.com/([^/?#]+)/board_(?:list|view)\b", re.I), _build),
]
