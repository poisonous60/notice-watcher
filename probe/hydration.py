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
_ID_KEYS = ("id", "articleId", "noticeId", "no", "slug", "uid", "uuid", "code")
_DATE_KEYS = ("publishedAt", "createdAt", "date", "regDate", "pubDate", "datetime", "updatedAt", "displayAt")


def find_list_in_json(blob: Any, *, min_items: int = 5) -> list[dict]:
    """블롭 안에서 글 목록일 가능성 있는 배열을 찾는다.

    리턴: [{path: "props.pageProps.news", count: N, sample: <첫 항목>}, ...]
    """
    found: list[dict] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, list):
            if len(node) >= min_items and node and isinstance(node[0], dict):
                first = node[0]
                if any(k in first for k in _TITLE_KEYS) and any(k in first for k in _ID_KEYS):
                    found.append({
                        "path": path,
                        "count": len(node),
                        "sample_keys": list(first.keys())[:20],
                        "sample_first": {k: _shorten(first.get(k)) for k in list(first.keys())[:8]},
                    })
            for i, item in enumerate(node[:50]):  # 너무 깊게 안 봄
                walk(item, f"{path}[{i}]")
        elif isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else k)

    walk(blob, "")
    return found


def _shorten(v: Any) -> Any:
    if isinstance(v, str):
        return v[:80]
    return v
