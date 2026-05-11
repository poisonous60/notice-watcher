"""Phase 7: 글 목록 후보 추출.

(a) HTML 반복 패턴
(b) Playwright HAR 트래픽에서 JSON API 후보
(c) Hydration JSON에서 글 목록
+ 첫 글 URL 추출
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .hydration import find_list_in_json


def html_repeating_patterns(html: str, base_url: str, *, min_children: int = 5) -> list[dict]:
    """같은 부모 안에서 같은 시그니처(태그+클래스)를 갖는 자식이 N개 이상인 노드 후보."""
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    candidates: list[dict] = []

    for parent in soup.find_all(True):
        if not isinstance(parent, Tag):
            continue
        children = [c for c in parent.find_all(recursive=False) if isinstance(c, Tag)]
        if len(children) < min_children:
            continue
        # 시그니처 그룹핑
        groups: dict[str, list[Tag]] = {}
        for c in children:
            sig = _signature(c)
            groups.setdefault(sig, []).append(c)
        for sig, group in groups.items():
            if len(group) < min_children:
                continue
            # 자식 안의 a 태그 href 공통 prefix
            hrefs = []
            for child in group:
                a = child if child.name == "a" else child.find("a", href=True)
                if a and a.has_attr("href"):
                    hrefs.append(a["href"])
            common_prefix = _common_url_prefix(hrefs) if hrefs else None
            url_pattern = _href_pattern(hrefs) if hrefs else None
            first_text = " ".join((group[0].get_text(" ", strip=True) or "").split())[:120]
            sample_url = urljoin(base_url, hrefs[0]) if hrefs else None

            selector = _css_selector(parent) + " > " + sig
            candidates.append({
                "selector": selector,
                "child_count": len(group),
                "first_text": first_text,
                "href_common_prefix": common_prefix,
                "href_pattern_guess": url_pattern,
                "sample_url": sample_url,
            })

    # 같은 selector 중복 제거 + 큰 순
    seen = set()
    deduped: list[dict] = []
    for c in sorted(candidates, key=lambda x: -x["child_count"]):
        if c["selector"] in seen:
            continue
        seen.add(c["selector"])
        deduped.append(c)
    return deduped[:15]


def _signature(tag: Tag) -> str:
    classes = ".".join(tag.get("class") or [])
    return f"{tag.name}.{classes}" if classes else tag.name


def _css_selector(tag: Tag) -> str:
    """매우 단순한 selector (id 우선, 없으면 tag + class)."""
    if tag.get("id"):
        return f"#{tag['id']}"
    classes = ".".join(tag.get("class") or [])
    return f"{tag.name}.{classes}" if classes else tag.name


_NUM_RE = re.compile(r"\d+")


def _common_url_prefix(hrefs: list[str]) -> Optional[str]:
    if not hrefs:
        return None
    s = hrefs[0]
    for h in hrefs[1:]:
        i = 0
        while i < min(len(s), len(h)) and s[i] == h[i]:
            i += 1
        s = s[:i]
        if not s:
            break
    return s or None


def _href_pattern(hrefs: list[str]) -> Optional[str]:
    """첫 href에서 숫자/슬러그 부분을 placeholder로 치환한 추측 패턴."""
    if not hrefs:
        return None
    h = hrefs[0]
    # 쿼리스트링의 숫자 값과 path 끝의 숫자 segment를 {n}으로 치환
    h = re.sub(r"(=)\d+", r"\1{n}", h)
    h = re.sub(r"/\d+(/|$)", r"/{n}\1", h)
    return h


def traffic_api_candidates(har_path: Path) -> list[dict]:
    """HAR 파일에서 JSON 응답 + 5개 이상 항목 배열을 가진 응답을 후보로."""
    if not har_path.exists():
        return []
    try:
        har = json.loads(har_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return []

    candidates: list[dict] = []
    entries = har.get("log", {}).get("entries", [])
    for entry in entries:
        req = entry.get("request", {})
        resp = entry.get("response", {})
        ct = ""
        for h in resp.get("headers", []):
            if h.get("name", "").lower() == "content-type":
                ct = h.get("value", "")
                break
        if "json" not in ct.lower():
            continue
        content = resp.get("content", {}) or {}
        text = content.get("text") or ""
        encoding = content.get("encoding")
        if encoding == "base64" and text:
            try:
                text = base64.b64decode(text).decode("utf-8", errors="replace")
            except Exception:
                continue
        if not text:
            continue
        try:
            data = json.loads(text)
        except Exception:
            continue
        list_hits = find_list_in_json(data, min_items=5)
        if not list_hits:
            continue
        candidates.append({
            "method": req.get("method"),
            "url": req.get("url"),
            "status": resp.get("status"),
            "content_type": ct,
            "list_hits": list_hits,
            "request_headers": {str(h.get("name", "")): str(h.get("value", "")) for h in (req.get("headers") or [])},
            "request_body_text": (req.get("postData") or {}).get("text"),
        })
    return candidates


# --------------------------------------------------------------------------- #
# 글 *본문* JSON API 후보 (목록이 아니라 단일 글 본문 — SPA 글 페이지가 XHR 로 본문을 받아올 때)
# --------------------------------------------------------------------------- #
_BODY_KEY_HINTS = re.compile(
    r"^(content|contents?|contenthtml|contentbody|contentstext|body|bodyhtml|bodytext|html|"
    r"article|articlecontents?|articlebody|text|desc|description|detail|details|message|"
    r"boardcontents?|noticecontents?|view|viewdata|writedata|maincontents?)$",
    re.IGNORECASE,
)
_HTMLISH_RE = re.compile(r"</[a-z][\w-]*>|<(?:p|div|br|img|span|h[1-6]|ul|li|table|strong)\b|&nbsp;|&lt;", re.IGNORECASE)


def _ids_in_url(url: str) -> set[str]:
    """URL(경로+쿼리)에서 4자리 이상 숫자 런 — post_id 추정용."""
    from urllib.parse import urlsplit
    sp = urlsplit(url or "")
    return set(re.findall(r"\d{4,}", (sp.path or "") + "?" + (sp.query or "")))


_MULTI_TLD = ("co.kr", "co.jp", "co.uk", "com.cn", "or.kr", "ne.jp", "go.kr", "ac.kr")


def _registrable(host: str) -> str:
    """host → 등록가능도메인 근사치 (PSL 없이): co.kr/co.jp 등은 3라벨, 그 외 2라벨."""
    parts = (host or "").lower().split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in _MULTI_TLD:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else (host or "").lower()


def _same_site(url_a: str, url_b: str) -> bool:
    """두 URL 이 같은 사이트(등록가능도메인)인가 — 광고/트래커(onetag.co.kr, criteo.com 등) 후보를 거르는 용도."""
    from urllib.parse import urlsplit
    ha, hb = urlsplit(url_a or "").netloc, urlsplit(url_b or "").netloc
    if not ha or not hb:
        return False
    return _registrable(ha) == _registrable(hb)


def _dig(obj: Any, path: list) -> Any:
    for k in path:
        obj = obj[k]
    return obj


def _walk_long_strings(node: Any, path: list, out: list, *, depth: int = 0, max_depth: int = 7, budget: Optional[list] = None) -> None:
    """JSON 안에서 '본문스러운' 긴 문자열들을 모은다. path = 키(str)/인덱스(int) 리스트(엔진의 from:json path 형식)."""
    if budget is None:
        budget = [5000]
    if budget[0] <= 0 or depth > max_depth:
        return
    budget[0] -= 1
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, str):
                vlen = len(v)
                htmlish = bool(_HTMLISH_RE.search(v))
                key_hit = bool(_BODY_KEY_HINTS.match(str(k)))
                if vlen >= 200 or (vlen >= 60 and (htmlish or key_hit)):
                    out.append({"path": path + [k], "key": str(k), "len": vlen, "html": htmlish, "key_hit": key_hit})
            else:
                _walk_long_strings(v, path + [k], out, depth=depth + 1, max_depth=max_depth, budget=budget)
    elif isinstance(node, list):
        for i, item in enumerate(node[:30]):
            _walk_long_strings(item, path + [i], out, depth=depth + 1, max_depth=max_depth, budget=budget)


def _har_entry_response_text(entry: dict, har_path: Path) -> str:
    """HAR 엔트리 응답 본문 텍스트 — text 인라인 / base64 / attach 외부파일 모두 처리."""
    content = (entry.get("response") or {}).get("content") or {}
    text = content.get("text") or ""
    if text and content.get("encoding") == "base64":
        try:
            text = base64.b64decode(text).decode("utf-8", errors="replace")
        except Exception:
            return ""
    if not text:
        fref = content.get("_file") or content.get("file")
        if fref:
            for cand in (har_path.parent / fref,
                         (har_path.parent / (har_path.stem + ".har_data")) / fref,
                         har_path.parent / "traffic.har_data" / fref):
                try:
                    if cand.exists():
                        return cand.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    pass
    return text


def traffic_article_body_candidates(har_path: Path, article_url: str = "", *, max_candidates: int = 6) -> list[dict]:
    """HAR 에서 '단일 글 본문' 을 담은 JSON 응답 후보를 점수순으로. (= traffic_api_candidates 의 본문판)

    각 후보: {method, url, status, content_type, request_headers, request_body_text,
              body_field_path(엔진 from:json path), body_len, body_looks_html, body_key, url_id_match, sample}
    """
    if not har_path.exists():
        return []
    try:
        har = json.loads(har_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return []
    want_ids = _ids_in_url(article_url)
    cands: list[dict] = []
    for entry in ((har.get("log") or {}).get("entries") or []):
        try:
            resp = entry.get("response") or {}
            req = entry.get("request") or {}
            ct = ""
            for h in resp.get("headers") or []:
                if str(h.get("name", "")).lower() == "content-type":
                    ct = h.get("value", "") or ""
                    break
            if "json" not in ct.lower():
                continue
            url = req.get("url") or ""
            # 광고/트래커 등 제3자 도메인 응답은 글 본문 API 가 아님 — 같은 사이트(또는 article_url 미지정 시 통과)만
            if article_url and url and not _same_site(url, article_url):
                continue
            text = _har_entry_response_text(entry, har_path)
            if not text or len(text) < 60:
                continue
            data = json.loads(text)
            hits: list[dict] = []
            _walk_long_strings(data, [], hits)
            if not hits:
                continue
            hits.sort(key=lambda h: (h["html"], h["key_hit"], h["len"]), reverse=True)
            best = hits[0]
            rbt = (req.get("postData") or {}).get("text")
            url_id_match = bool(want_ids and any(i in url for i in want_ids))
            body_id_match = bool(want_ids and rbt and any(i in rbt for i in want_ids))
            score = ((3 if url_id_match else 0) + (2 if body_id_match else 0)
                     + (2 if best["html"] else 0) + (1 if best["key_hit"] else 0) + min(2, best["len"] // 1000))
            try:
                sample = str(_dig(data, best["path"]))[:300]
            except Exception:  # noqa: BLE001
                sample = ""
            cands.append({
                "method": req.get("method"), "url": url, "status": resp.get("status"), "content_type": ct,
                "request_headers": {str(h.get("name", "")): str(h.get("value", "")) for h in (req.get("headers") or [])},
                "request_body_text": rbt,
                "body_field_path": best["path"], "body_len": best["len"], "body_looks_html": best["html"],
                "body_key": best["key"], "url_id_match": url_id_match, "sample": sample, "_score": score,
            })
        except Exception:  # noqa: BLE001  — 한 엔트리가 깨져도 나머지는 본다
            continue
    cands.sort(key=lambda c: c["_score"], reverse=True)
    for c in cands:
        c.pop("_score", None)
    return cands[:max_candidates]


def _article_url_score(u: Optional[str], base_host: str) -> int:
    """'진짜 글 페이지 URL' 같은 정도. (헤더의 myinfo/login 링크 같은 잡 후보를 거르기 위해)"""
    if not u:
        return -1
    from urllib.parse import urlsplit
    sp = urlsplit(u)
    s = 0
    if base_host and sp.netloc == base_host:
        s += 4                                    # 같은 호스트 (목록과 다른 호스트면 거의 글이 아님)
    if sp.path and sp.path not in ("", "/"):
        s += 1
    if re.search(r"\d{3,}", (sp.path or "") + "?" + (sp.query or "")):
        s += 2                                    # 글 ID 같은 숫자
    if re.search(r"(view|detail|article|notice|read|thread|post|bbs|board)", (sp.path or "").lower()):
        s += 1
    return s


def pick_first_article_url(
    *,
    html_candidates: list[dict],
    json_api_candidates: list[dict],
    hydration_candidates: list[dict],
    base_url: str,
    page_html: str,
) -> Optional[str]:
    """첫 글 URL 후보를 뽑는다. (HTML 반복 패턴의 sample_url 중 '글 페이지스러운' 걸 점수로 고른다 —
    예전엔 그냥 첫 번째를 썼는데, 헤더의 myinfo/login 같은 반복 링크가 첫 후보로 잡히면 엉뚱한 URL 이 됐음.)"""
    from urllib.parse import urlsplit
    base_host = urlsplit(base_url or "").netloc
    cand_urls = [c["sample_url"] for c in html_candidates if c.get("sample_url")]
    if cand_urls:
        best = max(cand_urls, key=lambda u: _article_url_score(u, base_host))
        if _article_url_score(best, base_host) >= 4:   # 최소 same-host 는 만족
            return best
        return cand_urls[0]                            # same-host 후보가 없으면 옛 동작(첫 후보)
    # hydration: 첫 항목의 slug/id로 URL 추측 (사이트마다 패턴 다름 → 리스크)
    if hydration_candidates and page_html:
        item = hydration_candidates[0].get("sample_first") or {}
        slug = item.get("slug") or item.get("id")
        if slug:
            return urljoin(base_url, str(slug))
    # JSON API 후보의 첫 항목 — 어댑터에서 정해야 하므로 None 반환
    return None


def write_list_candidates(
    out_dir: Path,
    *,
    html_candidates: list[dict],
    json_api_candidates: list[dict],
    hydration_candidates: list[dict],
    first_article_url: Optional[str],
) -> None:
    payload = {
        "html_repeating_patterns": html_candidates,
        "traffic_json_api_candidates": [
            {k: v for k, v in c.items() if k != "request_body_text"} for c in json_api_candidates
        ],
        "hydration_list_candidates": hydration_candidates,
        "first_article_url": first_article_url,
    }
    (out_dir / "list_candidates.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
