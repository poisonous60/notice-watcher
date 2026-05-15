"""URL tracking/analytics query 식별 — slug hash 와 recognizer fast-path 양쪽이 같은 표 본다.

배경: 사용자가 `?category=공식` 같은 *사이트 의미 query* 와 `?utm_source=fb` 같은 *추적용 query* 가
섞인 URL 을 들고 와도, 후자만 drop 한 *정규화된* URL 로 hash 계산 + recognizer 매칭하면 같은
게시판의 변형 URL 들이 한 slug 로 합쳐진다. dedupe 우회(`/preview` 폭주 → 워커 큐 채우기) 차단.

보수적 allowlist — 확실히 추적용이고 어디서도 사이트 의미로 쓰지 않는 키만. `ref` 처럼 사이트마다
다르게 쓰이는 키는 안 넣음 (예: github `?ref=branch`).

호출:
  - engine.slug.canonical_url (slug hash 계산)
  - engine.recognizers._common.qs (recognizer fast-path 판단)
"""
from __future__ import annotations


_TRACKING_QUERY_PREFIXES = ("utm_", "_hsenc", "_hsmi", "oly_")
_TRACKING_QUERY_KEYS = frozenset({
    "fbclid", "gclid", "gclsrc", "dclid",
    "_ga", "_gid", "_gac",
    "mc_cid", "mc_eid",
    "igshid", "yclid", "wbraid", "gbraid",
    "msclkid", "ttclid", "twclid",
})


def is_tracking_query(key: str) -> bool:
    if key in _TRACKING_QUERY_KEYS:
        return True
    return any(key.startswith(pre) for pre in _TRACKING_QUERY_PREFIXES)
