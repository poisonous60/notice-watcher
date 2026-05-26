"""Hydration JSON (__NEXT_DATA__/__NUXT__/__INITIAL_STATE__) 추출."""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from bs4 import BeautifulSoup

from ._heuristic import heuristic


_INLINE_NUXT_RE = re.compile(r"window\.__NUXT__\s*=\s*({.*?});", re.DOTALL)
_INLINE_INIT_RE = re.compile(r"window\.__INITIAL_STATE__\s*=\s*({.*?});", re.DOTALL)


@heuristic
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
_URL_KEYS = ("url", "link", "href", "permalink", "link_url", "path")
_DATE_KEYS = ("publishedAt", "createdAt", "date", "regDate", "pubDate", "datetime", "updatedAt", "displayAt")


@heuristic
def _looks_like_row(first: dict) -> Optional[str]:
    """dict 가 글 한 건처럼 보이면 그 '항목 dict' 까지의 하위 경로를 반환(없으면 None).
    "" = first 자체가 항목. "feed" = first["feed"] 가 항목(엔벨로프형: {feed:{title,feedId,...}, user:{...}, ...}).
    엔벨로프는 *딱 한 단계* 만 본다(과탐 방지)."""
    has_title = any(k in first for k in _TITLE_KEYS)
    has_identity = any(k in first for k in _ID_KEYS) or any(k in first for k in _URL_KEYS)
    if has_title and has_identity:
        return ""
    for k, v in first.items():
        if not isinstance(v, dict):
            continue
        has_nested_title = any(kk in v for kk in _TITLE_KEYS)
        has_nested_identity = any(kk in v for kk in _ID_KEYS) or any(kk in v for kk in _URL_KEYS)
        if has_nested_title and has_nested_identity:
            return str(k)
    return None


@heuristic
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


# --------------------------------------------------------------------------- #
# 인라인 JS / JSON-island 데이터 후보 — 목록이 정적 HTML 행이 아니라 <script> 안에 있을 때.
#   extract_hydration 이 __NEXT_DATA__/__NUXT__/__INITIAL_STATE__ 는 따로 다룬다 — 여기는 그 외:
#     · <script type="application/json|ld+json">{...}</script>  (Next.js streaming, JSON-LD 등)
#     · var/let/const X = [ {...}, ... ]                        (JSON 으로 파싱되는 배열 리터럴)
#     · X.push({...}) 가 반복                                    (다음카페 모바일: articles.push({dataid,fldid,title,...}))
#       — push 형은 보통 키에 따옴표 없는 JS 객체 리터럴이라 파싱 불가 → raw 샘플만 제공(handwritten 어댑터가 정규식 파싱).
# --------------------------------------------------------------------------- #
_JSON_ISLAND_TYPES = {"application/json", "application/ld+json"}
_ARRAY_ASSIGN_RE = re.compile(r"(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*\[")
_PUSH_RE = re.compile(r"\b([A-Za-z_$][\w$]*)\s*\.\s*push\s*\(\s*\{")
# analytics/태그매니저/광고 큐 — `X.push({...})` 가 반복되지만 글 목록이 아님 (dataLayer, _gaq, appier_q, fbq, _paq, gtag, ga, _hsq …)
_ANALYTICS_QUEUE_RE = re.compile(r"(datalayer|_?gaq|_?paq|appier_q|fbq|_?hsq|gtm|gtag|^ga$|adsbygoogle|amplitude|mixpanel|clarity|optimizely|criteo_q)", re.IGNORECASE)


@heuristic
def _balanced(s: str, start: int, open_ch: str, close_ch: str, *, limit: int = 400_000) -> Optional[tuple[str, int]]:
    """s[start] 가 open_ch 라 가정. 짝 맞는 close_ch 까지의 슬라이스와 그 다음 인덱스를 반환(없으면 None). 문자열 리터럴 안의 괄호는 무시."""
    depth = 0
    in_str: Optional[str] = None
    i = start
    n = min(len(s), start + limit)
    while i < n:
        ch = s[i]
        if in_str is not None:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
        elif ch in "\"'`":
            in_str = ch
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return s[start:i + 1], i + 1
        i += 1
    return None


@heuristic
def _looks_rowish(d: Any) -> bool:
    return isinstance(d, dict) and any(k in d for k in _TITLE_KEYS) and any(k in d for k in _ID_KEYS)


@heuristic
def extract_inline_data(html: str, *, max_candidates: int = 8) -> list[dict]:
    """페이지 안의 인라인 JSON/JS 에서 '글 목록' 일 만한 데이터 후보를 모은다 (각 후보 dict 의 'kind' 로 구분).

      kind="json_island": <script type="application/json|ld+json">{...}</script> — list_hits(find_list_in_json) 포함.
      kind="js_array"   : `var X = [ {...}, ... ]` 로 JSON 파싱되는 배열 — 원소가 글처럼 보일 때.
      kind="js_push"    : `X.push({...})` 가 3회+ 반복 — raw 샘플(samples_raw, 각 ≤400자)만. handwritten 어댑터가 파싱.

    digest 에 그대로 첨부되므로 작게 유지(총 ≤max_candidates 건, push 샘플 3건/400자).
    """
    if not html:
        return []
    out: list[dict] = []

    # 1) <script type=application/(ld+)json> islands
    try:
        soup = BeautifulSoup(html, "lxml")
        for sc in soup.find_all("script"):
            if len(out) >= max_candidates:
                break
            t = (sc.get("type") or "").strip().lower()
            if t not in _JSON_ISLAND_TYPES:
                continue
            raw = (sc.string or sc.get_text() or "").strip()
            if len(raw) < 30:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            hits = find_list_in_json(data, min_items=5)[:5]
            if not hits and not (isinstance(data, list) and len(data) >= 8 and _looks_rowish(data[0])):
                continue
            cand: dict[str, Any] = {
                "kind": "json_island",
                "script_id": sc.get("id"),
                "script_type": t,
                "list_hits": hits,
                "top_keys": (list(data.keys())[:20] if isinstance(data, dict) else f"[list len {len(data)}]"),
            }
            if isinstance(data, dict) and data.get("@type"):
                cand["schema_type"] = data.get("@type")   # ld+json — BreadcrumbList/FAQPage 등이면 글 목록이 아니다(LLM 이 보고 판단)
            out.append(cand)
    except Exception:  # noqa: BLE001
        pass

    # 2) `var X = [ ... ]` — JSON 으로 파싱되는 배열만 (원소가 글처럼 보일 때)
    for m in _ARRAY_ASSIGN_RE.finditer(html):
        if len(out) >= max_candidates:
            break
        name = m.group(1)
        br = m.end() - 1                          # 정규식이 '[' 에서 끝남
        sl = _balanced(html, br, "[", "]", limit=200_000)
        if not sl:
            continue
        chunk = sl[0]
        if len(chunk) < 40 or len(chunk) > 300_000:
            continue
        try:
            arr = json.loads(chunk)
        except Exception:
            continue
        if not (isinstance(arr, list) and len(arr) >= 5 and _looks_rowish(arr[0])):
            continue
        out.append({
            "kind": "js_array",
            "var": name,
            "count": len(arr),
            "sample_keys": list(arr[0].keys())[:20],
            "sample_first": _sample_node(arr[0]),
        })

    # 3) `X.push({ ... })` 가 반복 — var 별 카운트, 가장 많은 것의 raw 샘플
    push_groups: dict[str, list[str]] = {}
    scanned = 0
    for m in _PUSH_RE.finditer(html):
        scanned += 1
        if scanned > 5000:                        # 폭주 방지
            break
        name = m.group(1)
        sl = _balanced(html, m.end() - 1, "{", "}", limit=20_000)
        if not sl:
            continue
        push_groups.setdefault(name, []).append(sl[0])
    for name, objs in sorted(push_groups.items(), key=lambda kv: -len(kv[1])):
        if len(out) >= max_candidates:
            break
        if len(objs) < 3 or _ANALYTICS_QUEUE_RE.search(name):
            continue
        try:
            parsed_first = json.loads(objs[0])
        except Exception:
            parsed_first = None
        cand: dict[str, Any] = {
            "kind": "js_push",
            "var": name,
            "count": len(objs),
            "samples_raw": [(o[:400] + " …[truncated]") if len(o) > 400 else o for o in objs[:3]],
        }
        if isinstance(parsed_first, dict):
            cand["sample_keys"] = list(parsed_first.keys())[:20]
            cand["sample_first"] = _sample_node(parsed_first)
        out.append(cand)

    return out[:max_candidates]
