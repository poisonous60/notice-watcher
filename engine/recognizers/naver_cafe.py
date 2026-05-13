"""네이버 카페 → NaverCafeAdapter(목록/공지/본문 JSON API).

cafe_id/menu_id 는 URL 에서 추출. 비공개·등급제한 게시판이면 본문 API 가 401/403 →
어댑터가 본문 비워 반환(우회 안 함; storage_state 로그인 필요).
"""
from __future__ import annotations

import re
from typing import Optional

from ._common import qs

NAME = "naver-cafe"

_NOTE = ("네이버 카페 — known-platform 자동 인식. 손어댑터 NaverCafeAdapter 가 목록/공지/본문 JSON API"
         "(apis.naver.com/cafe-web/..., article.cafe.naver.com/gw/...)를 직접 호출. cafe_id/menu_id 는 URL 에서. "
         "비공개·등급제한 게시판이면 본문 API 가 401/403 → 어댑터가 본문 비워 반환(우회 안 함; storage_state 로그인 필요).")


def _cfg(cafe_id: int, menu_id: int, url: str) -> dict:
    return {
        "version": 1, "site": "cafe.naver.com", "board": f"cafe{cafe_id}/menu{menu_id}",
        "strategy": "handwritten", "adapter": "NaverCafeAdapter",
        "kwargs": {"cafe_id": int(cafe_id), "menu_id": int(menu_id), "include_notices": True, "timeout": 15.0},
        "_source_url": url, "_note": _NOTE,
    }


# https://cafe.naver.com/f-e/cafes/30291108/menus/6?viewType=L  (신 UI 메뉴 URL)
def _menu(m: "re.Match", url: str) -> Optional[dict]:
    return _cfg(int(m.group(1)), int(m.group(2)), url)


# https://cafe.naver.com/f-e/cafes/30291108/articles/12345?menuid=6&...  (신 UI 글 URL — menuid 가 쿼리에)
def _article(m: "re.Match", url: str) -> Optional[dict]:
    # menuid 쿼리가 잘려서 없으면 어느 메뉴인지 알 수 없으니 None → 일반 파이프라인 폴백
    menu_id = qs(url).get("menuid") or qs(url).get("menuId")
    if not (menu_id and str(menu_id).isdigit()):
        return None
    return _cfg(int(m.group(1)), int(menu_id), url)


# https://cafe.naver.com/ArticleList.nhn?search.clubid=30291108&search.menuid=6  (구 UI)
def _legacy(m: "re.Match", url: str) -> Optional[dict]:
    q = qs(url)
    club = q.get("search.clubid") or q.get("clubid")
    menu = q.get("search.menuid") or q.get("menuid")
    if not (club and menu and str(club).isdigit() and str(menu).isdigit()):
        return None
    return _cfg(int(club), int(menu), url)


PATTERNS = [
    (re.compile(r"//(?:m\.)?cafe\.naver\.com/[A-Za-z0-9_-]+/cafes/(\d+)/menus/(\d+)\b", re.I), _menu),
    (re.compile(r"//(?:m\.)?cafe\.naver\.com/[A-Za-z0-9_-]+/cafes/(\d+)/articles/\d+\b", re.I), _article),
    (re.compile(r"//(?:m\.)?cafe\.naver\.com/ArticleList\.nhn\b", re.I), _legacy),
]
