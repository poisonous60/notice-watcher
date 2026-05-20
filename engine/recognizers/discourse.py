"""Discourse 포럼 → DiscourseAdapter (공개 JSON API).

URL 폼 (root /latest 만):
  - https://<host>/latest
  - https://<host>/latest?ascending=...&order=...

추가 폼 (`/c/<cat>/<id>`, `/t/<slug>/<id>`) 은 일반 파이프라인.

자동 파이프 실패 패턴 (probe diagnosis):
  `posts_nonempty: 0건` (httpx_html `tbody.topic-list-body > tr.topic-list-item`) — `/latest` 가
  Ember.js 렌더라 정적 HTML 에 topic rows 없음. + feed_candidates>=1 (RSS) 또는 attempt 3 이
  `httpx_json list_path=['topic_list','topics']` 인데 본문 fetch 가 막힘.
  → 진짜 솔루션은 `<base>/latest.json` + `<base>/t/<id>.json` JSON API. 손어댑터로 봉합.

오인 매칭 안전망:
  `/latest` 는 Discourse 외에도 쓰는 사이트 있음 (예: 미디어 사이트). 잘못 매칭되면
  DiscourseAdapter.fetch_list 가 not-Discourse-shaped JSON 을 받아 빈 목록 반환 → register.py
  의 `register_recognized` 가 빈 목록 보고 일반 파이프라인으로 폴백 (cfg discard).
"""
from __future__ import annotations

import re
from typing import Optional

NAME = "discourse"

_NOTE = ("Discourse 포럼 — known-platform 자동 인식. 손어댑터 DiscourseAdapter 가 "
         "<base>/latest.json (목록) + <base>/t/<id>.json (본문) JSON API 를 직접 호출. "
         "/latest 정적 HTML 은 Ember.js shell 이라 row 가 정적에 없음 — JSON API 가 안정.")

_LATEST_RE = re.compile(r"^https?://([^/?#]+)/latest/?(?:\?|#|$)", re.I)


def _build(m: "re.Match", url: str) -> Optional[dict]:
    host = m.group(1).lower()
    if not host or "." not in host:
        return None
    base_url = f"https://{host}"
    return {
        "version": 1, "site": host, "board": "latest",
        "strategy": "handwritten", "adapter": "DiscourseAdapter",
        "kwargs": {"base_url": base_url},
        "_slug_board": host,
        "_source_url": f"{base_url}/latest",
        "_note": _NOTE,
    }


PATTERNS = [
    (_LATEST_RE, _build),
]
