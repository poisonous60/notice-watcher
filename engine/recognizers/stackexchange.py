"""StackExchange questions pages -> public StackExchange API questions feed.

URL form:
  - https://stackoverflow.com/questions
  - https://superuser.com/questions
  - https://askubuntu.com/questions
  - https://serverfault.com/questions
  - https://mathoverflow.net/questions
  - https://<site>.stackexchange.com/questions

Why API, not HTML:
  The `/questions` HTML pages can return 403 or an empty bot-challenge shell to
  plain httpx. The official StackExchange API exposes the same recent-question
  stream as JSON and works through the existing `httpx_json` strategy.

False-positive boundary:
  Only the StackExchange network host allow-list is accepted, and only the
  literal `/questions` board path maps to the feed. Tags, individual questions,
  and arbitrary StackExchange paths fall back to the generic pipeline.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import quote, urlsplit

from ._common import UA, qs

NAME = "stackexchange"

_ALLOWED_EXACT_HOSTS = frozenset({
    "stackoverflow.com",
    "superuser.com",
    "askubuntu.com",
    "serverfault.com",
    "mathoverflow.net",
})

_QUESTIONS_RE = re.compile(r"^https?://([^/?#]+)/questions/?(?:[?#].*)?$", re.I)
_DEFAULT_SORT = "creation"
_TAB_SORTS = {
    "newest": "creation",
    "active": "activity",
    "votes": "votes",
    "hot": "hot",
    "week": "week",
    "month": "month",
}

_NOTE = (
    "StackExchange questions board — known-platform 자동 인식. HTML `/questions` 는 "
    "anti-bot 403/빈 DOM 이 날 수 있어 공식 StackExchange API `/2.3/questions` 를 "
    "httpx_json 으로 수집한다. post_id=question_id, title/link/creation_date/body 를 추출한다."
)


def _allowed_host(host: str) -> bool:
    h = host.lower().removeprefix("www.")
    return h in _ALLOWED_EXACT_HOSTS or h.endswith(".stackexchange.com")


def _api_site(host: str) -> str:
    if host.endswith(".stackexchange.com"):
        return host.removesuffix(".stackexchange.com")
    return host.removesuffix(".com").removesuffix(".net")


def _sort_for(url: str) -> str:
    q = qs(url)
    sort = (q.get("sort") or "").strip().lower()
    if sort:
        return sort
    tab = (q.get("tab") or "").strip().lower()
    return _TAB_SORTS.get(tab, _DEFAULT_SORT)


def _build(m: "re.Match", url: str) -> Optional[dict]:
    parts = urlsplit(url)
    host = (parts.netloc or m.group(1) or "").strip().lower().removeprefix("www.")
    if not _allowed_host(host):
        return None
    sort = _sort_for(url)
    api_site = _api_site(host)
    list_url = (
        "https://api.stackexchange.com/2.3/questions"
        f"?order=desc&sort={sort}&site={api_site}&pagesize=30&filter=withbody"
    )
    article_url = (
        "https://api.stackexchange.com/2.3/questions/{post_id}"
        f"?order=desc&sort=activity&site={api_site}&filter=withbody"
    )
    return {
        "version": 1,
        "site": host,
        "board": "questions",
        "strategy": "httpx_json",
        "headers": {
            "User-Agent": UA,
            "Accept": "application/json,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
            "Referer": f"https://{host}/questions",
        },
        "timeout": 15,
        "polite_sleep": {"min": 1, "max": 1},
        "list": {
            "url_template": list_url,
            "pagination": {"kind": "none"},
            "list_path": ["items"],
            "include_notices": True,
            "fields": {
                "post_id": [
                    {"from": "json", "path": ["question_id"], "transform": [["to_str"]]},
                ],
                "title": [
                    {"from": "json", "path": ["title"], "transform": [["html_unescape"], ["collapse_ws"]]},
                ],
                "url": [
                    {"from": "json", "path": ["link"]},
                    {"from": "template", "value": f"https://{host}/q/{{post_id}}"},
                ],
                "published_at": [
                    {
                        "from": "json",
                        "path": ["creation_date"],
                        "transform": [["unixtime_to_iso", "Z", "s"]],
                    },
                ],
                "summary": [
                    {
                        "from": "json",
                        "path": ["body"],
                        "transform": [["collapse_ws"]],
                    },
                ],
            },
        },
        "article": {
            "fetch_kind": "json",
            "url_template": article_url,
            "data_path": ["items", 0],
            "content": [{"from": "json", "path": ["body"]}],
            "re_extract": True,
        },
        "_slug_board": (
            f"{host}_questions"
            if sort == _DEFAULT_SORT
            else f"{host}_questions_sort_{quote(sort, safe='')}"
        ),
        "_source_url": list_url,
        "_note": _NOTE,
    }


PATTERNS = [
    (_QUESTIONS_RE, _build),
]
