"""Hydration JSON (__NEXT_DATA__/__NUXT__/__INITIAL_STATE__) 추출."""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from bs4 import BeautifulSoup


_INLINE_NUXT_RE = re.compile(r"window\.__NUXT__\s*=\s*({.*?});", re.DOTALL)
_INLINE_INIT_RE = re.compile(r"window\.__INITIAL_STATE__\s*=\s*({.*?});", re.DOTALL)


def extract_hydration(html: str) -> dict[str, Any]:
    """발견된 hydration JSON들을 dict로 묶어 반환."""
    out: dict[str, Any] = {}
    if not html:
        return out

    soup = BeautifulSoup(html, "lxml")

    nd = soup.find("script", id="__NEXT_DATA__")
    if nd and nd.string:
        try:
            out["__NEXT_DATA__"] = json.loads(nd.string)
        except Exception as e:
            out["__NEXT_DATA__"] = {"_parse_error": str(e), "_raw": nd.string[:1000]}

    for m in _INLINE_NUXT_RE.finditer(html):
        try:
            out["__NUXT__"] = json.loads(m.group(1))
            break
        except Exception:
            pass

    for m in _INLINE_INIT_RE.finditer(html):
        try:
            out["__INITIAL_STATE__"] = json.loads(m.group(1))
            break
        except Exception:
            pass

    return out


_TITLE_KEYS = ("title", "name", "subject", "headline")
_ID_KEYS = ("id", "articleId", "noticeId", "no", "slug", "uid", "uuid", "code",
            "feedId", "postId", "articleNo", "contentId", "seq")
_DATE_KEYS = ("publishedAt", "createdAt", "date", "regDate", "pubDate", "datetime", "updatedAt", "displayAt")


def _looks_like_row(first: dict) -> Optional[str]:
    """dict 가 글 한 건처럼 보이면 그 '항목 dict' 까지의 하위 경로를 반환(없으면 None).
    "" = first 자체가 항목. "feed" = first["feed"] 가 항목(엔벨로프형: {feed:{title,feedId,...}, user:{...}, ...}).
    엔벨로프는 *딱 한 단계* 만 본다(과탐 방지)."""
    if any(k in first for k in _TITLE_KEYS) and any(k in first for k in _ID_KEYS):
        return ""
    for k, v in first.items():
        if isinstance(v, dict) and any(kk in v for kk in _TITLE_KEYS) and any(kk in v for kk in _ID_KEYS):
            return str(k)
    return None


def find_list_in_json(blob: Any, *, min_items: int = 5) -> list[dict]:
    """블롭 안에서 글 목록일 가능성 있는 배열을 찾는다.

    리턴: [{path, count, sample_keys, sample_first, item_subpath}, ...]
      item_subpath: 각 배열 원소 안에서 '항목 dict' 가 한 단계 더 들어가 있으면 그 키(엔진 config 의 item_path 1단계).
                    "" 면 원소 자체가 항목.
    """
    found: list[dict] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, list):
            if len(node) >= min_items and node and isinstance(node[0], dict):
                first = node[0]
                sub = _looks_like_row(first)
                if sub is not None:
                    found.append({
                        "path": path,
                        "count": len(node),
                        "item_subpath": sub,  # "" = 원소 자체가 항목; "feed" = 원소.feed 가 항목(엔벨로프). 필드 path 는 원소 기준으로 잡으면 됨.
                        "sample_keys": list(first.keys())[:20],
                        "sample_first": _sample_node(first),  # 원소 구조 2단계 — 엔벨로프면 형제 dict(user/feedLink/board…)들도 보임
                    })
            for i, item in enumerate(node[:50]):  # 너무 깊게 안 봄
                walk(item, f"{path}[{i}]")
        elif isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else k)

    walk(blob, "")
    return found


def _sample_node(d: dict, *, max_keys: int = 14) -> dict:
    """배열 원소 dict 의 샘플 — 값이 dict 면 그 키 목록을, 그 외엔 짧게. (엔벨로프형에서 형제 객체 구조까지 한눈에)"""
    out: dict[str, Any] = {}
    for k in list(d.keys())[:max_keys]:
        v = d[k]
        if isinstance(v, dict):
            out[k] = {"_keys": list(v.keys())[:12]}
        elif isinstance(v, list):
            out[k] = f"[list len {len(v)}]"
        else:
            out[k] = _shorten(v)
    return out


def _shorten(v: Any) -> Any:
    if isinstance(v, str):
        return v[:80]
    return v
