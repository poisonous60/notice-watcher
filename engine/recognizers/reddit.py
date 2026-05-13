"""Reddit 서브레딧 → RedditAdapter (공개 .json 엔드포인트).

URL 의 sort(`/hot`, `/top/?t=day`)/flair(`?f=flair_name:"X"`)도 파싱해서 kwargs 에 반영.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlsplit

from ._common import qs

NAME = "reddit"

_SORTS = {"hot", "new", "top", "rising"}
_TIMES = {"hour", "day", "week", "month", "year", "all"}
_NOT_SUB = {"comments", "wiki", "about", "submit", "search"}


def _build(m: "re.Match", url: str) -> Optional[dict]:
    sub = m.group(1)
    if not sub or sub.lower() in _NOT_SUB:
        return None
    path = urlsplit(url).path or ""
    needle = "/r/" + sub.lower()
    i = path.lower().find(needle)
    rest = path[i + len(needle):].strip("/") if i != -1 else ""
    first = rest.split("/", 1)[0].lower() if rest else ""
    if first == "comments":
        return None  # 단일 글 URL — 게시판 워처 대상 아님 → 일반 파이프라인으로 폴백
    sort = first if first in _SORTS else "new"
    q = qs(url)
    time_filter = q.get("t") if (sort == "top" and q.get("t") in _TIMES) else "day"
    flair = None
    fm = re.search(r'flair_name:\s*"?([^"&]+)"?', q.get("f") or "", re.I)
    if fm:
        flair = fm.group(1).strip() or None

    kwargs: dict = {"subreddit": sub}
    if sort != "new":
        kwargs["sort"] = sort
        if sort == "top":
            kwargs["time_filter"] = time_filter
    if flair:
        kwargs["flair"] = flair

    board_parts = [sub]
    if sort != "new":
        board_parts.append(sort + (f":{time_filter}" if sort == "top" else ""))
    if flair:
        board_parts.append(f"flair={flair}")
    sort_seg = "" if sort == "new" else f"/{sort}"
    src = f"https://www.reddit.com/r/{sub}{sort_seg}/" + (f"?t={time_filter}" if sort == "top" else "")
    return {
        "version": 1, "site": "reddit.com", "board": "/".join(board_parts),
        "strategy": "handwritten", "adapter": "RedditAdapter", "kwargs": kwargs,
        "_source_url": src,
        "_note": ("Reddit 서브레딧 — known-platform 자동 인식. 손어댑터 RedditAdapter 가 공개 .json 엔드포인트"
                  "(목록 /r/{sub}/{sort}.json, 본문 permalink+/.json) 사용. 기본 sort=new(새 글 전부); URL 이 /r/X/hot/ 또는 /top/?t=day 면 그 정렬, "
                  "?f=flair_name:\"...\" 면 그 플레어 글만(창작/공식소식 탭 효과). 자동 인식되면 sort/flair 외의 옵션은 "
                  "configs/<slug>.json 을 직접 손봐서(kwargs.include_stickied 등) register.py --config 로 재등록. "
                  "robots.txt 는 Disallow:/ 라 회색지대 — 저빈도 개인용·UA+polite_sleep·우회 없음."),
    }


PATTERNS = [
    (re.compile(r"//(?:www\.|old\.|new\.|np\.|m\.|i\.)?reddit\.com/r/([A-Za-z0-9_]+)", re.I), _build),
]
