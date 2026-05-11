"""strategy 레지스트리.

각 strategy 모듈은 다음 async 함수를 노출한다:
  open_session(adapter)  /  close_session(adapter)
  fetch_list(adapter, *, page, page_size) -> list[NoticePost]
  fetch_article(adapter, post) -> NoticePost
"""
from __future__ import annotations

from . import httpx_html, httpx_json, playwright_html

STRATEGIES = {
    "httpx_html": httpx_html,
    "httpx_json": httpx_json,
    "playwright_html": playwright_html,  # 모듈 자체는 playwright 없어도 import 됨 — open_session 에서만 필요
}


def get_strategy(name: str):
    mod = STRATEGIES.get(name)
    if mod is None:
        raise KeyError(f"미지원 strategy: {name!r} (지원: {sorted(STRATEGIES)} + 'handwritten')")
    return mod
