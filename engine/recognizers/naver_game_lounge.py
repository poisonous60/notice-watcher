"""네이버 게임 라운지 → httpx_json (내부 API: comm-api.game.naver.com/.../feed)."""
from __future__ import annotations

import re
from typing import Optional

from ._common import UA

NAME = "naver-game-lounge"


def _build(m: "re.Match", url: str) -> Optional[dict]:
    game = m.group(1)
    board_id = m.group(2)
    base = f"https://comm-api.game.naver.com/nng_main/v1/community/lounge/{game}"
    view_url = f"https://game.naver.com/lounge/{game}/board/{board_id}"
    return {
        "version": 1, "site": "game.naver.com", "board": f"lounge/{game}/{board_id}", "strategy": "httpx_json",
        "_slug_board": f"{game}_{board_id}",
        "headers": {
            "User-Agent": UA, "Accept": "application/json, text/plain, */*", "Accept-Language": "ko-KR,ko;q=0.9",
            "Origin": "https://game.naver.com", "Referer": view_url,
            "front-client-platform-type": "PC", "front-client-product-type": "web",
        },
        "timeout": 15.0,
        "list": {
            "url_template": f"{base}/feed?boardId={board_id}&buffFilteringYN=N&limit=25&offset=0&order=NEW",
            "pagination": {"kind": "offset", "offset_param": "offset", "size_param": "limit", "page_unit": 25},
            "success_when": {"path": ["code"], "equals": 200},
            "list_path": ["content", "feeds"],
            "fields": {
                "post_id": [{"from": "json", "path": ["feed", "feedId"]}],
                "title": [{"from": "json", "path": ["feed", "title"]}],
                "url": [{"from": "json", "path": ["feedLink", "pc"]},
                        {"from": "template", "value": f"https://game.naver.com/lounge/{game}/board/detail/{{post_id}}"}],
                "published_at": [{"from": "json", "path": ["feed", "createdDate"], "transform": [["iso8601", ["%Y%m%d%H%M%S"], "+09:00"]]}],
                "author": [{"from": "json", "path": ["user", "nickname"]}],
                "category": [{"from": "json", "path": ["board", "boardName"]}],
                "cover_image": [{"from": "json", "path": ["feed", "repImageUrl"]}],
            },
        },
        "article": {
            "url_template": f"{base}/feed/{{post_id}}", "fetch_kind": "json",
            "success_when": {"path": ["code"], "equals": 200}, "data_path": ["content"],
            "content": [{"from": "json", "path": ["feed", "contents"]}],
        },
        "_source_url": view_url,
        "_note": (f"네이버 게임 라운지({game} board {board_id}) — known-platform 자동 인식. 목록 comm-api.game.naver.com/.../feed?boardId={board_id}&order=NEW "
                  "(offset 페이징, success code==200, list_path content.feeds, 엔트리 안에 feed/user/feedLink/board 서브객체), 본문 .../feed/{feedId} → content.feed.contents. "
                  "헤더는 UA + front-client-platform-type:PC + front-client-product-type:web + Referer/Origin."),
    }


PATTERNS = [
    (re.compile(r"//game\.naver\.com/lounge/([^/?#]+)/board/(\d+)\b", re.I), _build),
]
