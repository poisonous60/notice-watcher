"""Steam 앱 뉴스 피드 → httpx_html.

URL 폼 (둘 다 같은 appid → 같은 피드 config 로 정규화):
  - https://store.steampowered.com/feeds/news/app/<appid>/   (RSS 피드 — 실제 폴링 대상)
  - https://store.steampowered.com/news/app/<appid>/         (HTML 허브 — 사람이 브라우저에서 복사하는 URL)
  - board = <appid> (게임 store appid). URL path 의 숫자 segment.
  - 둘 다 list.url_template 은 /feeds/news/app/{board}/ (RSS) 로 빌드 — 허브 입력도 피드를 폴링.
  - 다음은 이 피드가 아님(다른 종류 페이지 — 매칭 안 됨):
      · /feeds/daily_deals.xml, /feeds/news.xml (appid 없는 전역 피드 — 구조 다름)
      · /news/app/<appid>/view/<id> (단일 article)

승급 출처: 자동생성된 개별 config 10건(app/105600·440·570·730·294100·413150·570·1086940·
  1091500·1145360·1245620)이 모두 store.steampowered.com/feeds/news/app/<appid>/ 폼 →
  recognizer-extension 으로 묶음 (2026-05-20).
  같은 cluster 의 daily_deals.xml·news.xml 2건은 appid 슬롯 없고 구조가 달라 제외.

주의 — 기존 자동생성 config 와 *기능 필드 byte-match 안 함*:
  LLM 이 멤버마다 다른 헤더·article selector·url transform·enrich·polite_sleep 를 뽑았다
  (570 은 board="app/570" 로 malformed). 이 recognizer 는 그 noise 를 교정한 *canonical* config —
  Steam 앱 뉴스 RSS 구조(channel>item, guid=/view/<id>, pubDate RFC822, enclosure)는 appid 불문
  동일하므로 robust skeleton 하나로 충분. 따라서 round-trip 검증은 "기존 config 재현"이 아니라
  "각 멤버 URL → board=appid·url_template 정확 추출 + 같은-host 다른-종류 negative"
  (test_steam_news.py 참고).
"""
from __future__ import annotations

import re
from typing import Optional

from ._common import UA

NAME = "steam-news"

# /feeds/news/app/<appid>/ (RSS 피드) — appid 숫자 segment. end anchor 로 .../view/(article) 제외.
_RE_FEED = re.compile(
    r"//store\.steampowered\.com/feeds/news/app/(\d+)/?(?:[?#].*)?$", re.I
)
# /news/app/<appid>/ (HTML 허브 — 사람-paste). end anchor 가 .../view/<id>(article) 를 배제.
# /feeds/daily_deals.xml·news.xml 은 /news/app/ 아니라 자동 배제.
_RE_HUB = re.compile(
    r"//store\.steampowered\.com/news/app/(\d+)/?(?:[?#].*)?$", re.I
)


def _build(m: "re.Match", url: str) -> Optional[dict]:
    appid = m.group(1)
    feed_url = f"https://store.steampowered.com/feeds/news/app/{appid}/"
    return {
        "version": 1,
        "site": "store.steampowered.com",
        "board": appid,
        "strategy": "httpx_html",
        "_slug_board": appid,
        "headers": {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
            "Referer": feed_url,
        },
        "timeout": 15,
        "list": {
            "url_template": "https://store.steampowered.com/feeds/news/app/{board}/",
            "pagination": {"kind": "none"},
            "row_selector": "channel > item",
            "fields": {
                "post_id": [
                    {
                        "from": "css",
                        "selector": "guid",
                        "text": True,
                        "transform": [["regex_extract", "/view/(\\d+)"]],
                    }
                ],
                "title": [
                    {
                        "from": "css",
                        "selector": "title",
                        "text": True,
                        "transform": [["collapse_ws"]],
                    }
                ],
                "url": [
                    {
                        "from": "css",
                        "selector": "guid",
                        "text": True,
                        "transform": [["strip"]],
                    },
                    {
                        "from": "template",
                        "value": "https://store.steampowered.com/news/app/{board}/view/{post_id}",
                    },
                ],
                "published_at": [
                    {
                        "from": "css",
                        "selector": "pubDate",
                        "text": True,
                        "transform": [["iso8601", ["%a, %d %b %Y %H:%M:%S %z"]]],
                    }
                ],
                "summary": [
                    {
                        "from": "css",
                        "selector": "description",
                        "text": True,
                        "transform": [["html_unescape"], ["collapse_ws"]],
                    }
                ],
                "cover_image": [
                    {"from": "css", "selector": "enclosure", "attr": "url"}
                ],
            },
        },
        "article": {
            "url_template": "https://store.steampowered.com/news/app/{board}/view/{post_id}",
            "fetch_kind": "html",
            "body_empty_acceptable": True,
            "content": [
                {"from": "css", "selector": "div.news_postbody", "html": True},
                {"from": "css", "selector": "div.news_post_body", "html": True},
                {"from": "css", "selector": "div.news_content", "html": True},
                {"from": "css", "selector": "div.bb_content", "html": True},
                {"from": "css", "selector": "body", "html": True},
            ],
        },
        "_source_url": feed_url,
        "_note": (
            f"Steam 앱 뉴스 피드(appid={appid}) — known-platform 자동 인식. 리스트 "
            "store.steampowered.com/feeds/news/app/<appid>/ (channel>item 행), "
            "post_id 는 guid 의 /view/<id> 에서 추출, title <title>, pubDate RFC822, "
            "summary description(html_unescape), cover enclosure[url], 본문 div.news_postbody 등. "
            "board=appid 는 URL path 에서 추출."
        ),
    }


PATTERNS = [
    (_RE_FEED, _build),
    (_RE_HUB, _build),
]
