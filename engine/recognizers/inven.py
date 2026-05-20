"""인벤(inven.co.kr) 게시판 → httpx_html.

URL 폼: https://www.inven.co.kr/board/<game>/<board_id>
  - game = 게임/카테고리 slug (ff14, lol, lostark, maple, party …). path 첫 segment.
  - board_id = 게시판 숫자 id. 두 변수 모두 URL path 에서 추출 → builder 결정적 재현.
  - 개별 글은 .../board/<game>/<id>/<post_id> (segment 1개 더) → 매칭 제외 (board 목록만).

승급 출처: 자동생성 개별 config 6건(ff14/4467·party/6510·lostark/4811·maple/2304·lol/4625·party/6181).
6건이 url_template 표현·selector·title 전략이 제각각이었으나(LLM noise) — 라이브 probe 결과
6개 board 모두 **동일한 단일 CMS DOM** 임을 확인(list: form board_list1 / td.num span / a.subject-link,
article: #powerbbsContent + div.articleView 둘 다 존재). 따라서 어느 noisy 멤버도 canonical 로 채택하지 않고
라이브 검증한 selector 로 새로 합성 (2026-05-20). 자세히 docs/cases/inven-recognizer.md.
"""
from __future__ import annotations

import re
from typing import Optional

from ._common import UA

NAME = "inven"

# /board/<game>/<board_id> — board_id 뒤에 또 /<post_id> 가 오면(개별 글) 매칭 X.
_RE = re.compile(
    r"//(?:www\.)?inven\.co\.kr/board/([^/?#]+)/(\d+)(?:[?#]|/?$)",
    re.I,
)


def _build(m: "re.Match", url: str) -> Optional[dict]:
    game = m.group(1)
    board_id = m.group(2)
    list_url = f"https://www.inven.co.kr/board/{game}/{board_id}"
    return {
        "version": 1,
        "site": "www.inven.co.kr",
        "board": f"{game}/{board_id}",
        "strategy": "httpx_html",
        "_slug_board": f"{game}_{board_id}",
        "headers": {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Upgrade-Insecure-Requests": "1",
            "Referer": list_url,
        },
        "timeout": 15,
        "list": {
            "url_template": f"https://www.inven.co.kr/board/{game}/{board_id}",
            "pagination": {"kind": "query_param", "page_param": "p"},
            "row_selector": "form[name='board_list1'] tbody > tr",
            "row_required_selector": "a.subject-link",
            "include_notices": True,
            "fields": {
                # post_id: href 마지막 숫자 segment — 공지 행도 href 엔 id 있어 td.num 보다 견고.
                "post_id": [
                    {
                        "from": "attr",
                        "selector": "a.subject-link",
                        "attr": "href",
                        "transform": [["regex_extract", r"/board/[^/]+/\d+/(\d+)"]],
                    }
                ],
                "title": [
                    {
                        "from": "css",
                        "selector": "a.subject-link",
                        "text": True,
                        "transform": [["collapse_ws"]],
                    }
                ],
                "url": [
                    {
                        "from": "attr",
                        "selector": "a.subject-link",
                        "attr": "href",
                        "transform": [["urljoin", "https://www.inven.co.kr"]],
                    }
                ],
                "author": [
                    {
                        "from": "css",
                        "selector": "td.user .layerNickName",
                        "text": True,
                        "transform": [["collapse_ws"]],
                    }
                ],
                "category": [
                    {
                        "from": "css",
                        "selector": "a.subject-link .category",
                        "text": True,
                        "transform": [["collapse_ws"], ["strip_brackets"]],
                    }
                ],
                # td.date: 오늘 글은 'HH:MM', 그 외 'MM-DD' — iso8601 가 포맷 순서대로 시도.
                "published_at": [
                    {
                        "from": "css",
                        "selector": "td.date",
                        "text": True,
                        "transform": [["iso8601", ["%H:%M", "%m-%d"], "+09:00"]],
                    },
                    {"from": "css", "selector": "td.date", "text": True},
                ],
            },
        },
        "article": {
            "fetch_kind": "html",
            "content": [
                {"from": "css", "selector": "#powerbbsContent", "html": True},
                {"from": "css", "selector": "div.articleView div.articleMain", "html": True},
                {"from": "css", "selector": "div.articleContent .contentBody", "html": True},
            ],
            "enrich": {
                "title": [
                    {
                        "from": "css",
                        "selector": "div.articleTitle h1",
                        "text": True,
                        "transform": [["collapse_ws"]],
                    }
                ],
                "published_at": [
                    {
                        "from": "css",
                        "selector": "div.articleDate",
                        "text": True,
                        "transform": [["collapse_ws"], ["iso8601", ["%Y-%m-%d %H:%M"], "+09:00"]],
                    }
                ],
                "author": [
                    {
                        "from": "css",
                        "selector": "div.articleWriter",
                        "text": True,
                        "transform": [["collapse_ws"]],
                    }
                ],
            },
        },
        "_source_url": list_url,
        "_note": (
            f"인벤 게시판(game={game}, board={board_id}) — known-platform 자동 인식. "
            "목록 form[name=board_list1] tbody>tr, post_id=a.subject-link href 숫자, "
            "title/url=a.subject-link, author=td.user .layerNickName, date=td.date(HH:MM|MM-DD). "
            "본문 #powerbbsContent→articleView fallback, articleDate=%Y-%m-%d %H:%M. "
            "game+board 둘 다 URL path 추출. p 쿼리 페이징."
        ),
    }


PATTERNS = [
    (_RE, _build),
]
