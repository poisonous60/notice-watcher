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
            "request_headers": {h["name"]: h["value"] for h in req.get("headers", [])},
            "request_body_text": (req.get("postData") or {}).get("text"),
        })
    return candidates


def pick_first_article_url(
    *,
    html_candidates: list[dict],
    json_api_candidates: list[dict],
    hydration_candidates: list[dict],
    base_url: str,
    page_html: str,
) -> Optional[str]:
    """가장 큰 후보에서 첫 글 URL을 뽑는다."""
    # 1) HTML 반복 패턴: sample_url 있으면 우선
    for c in html_candidates:
        if c.get("sample_url"):
            return c["sample_url"]
    # 2) hydration: 첫 항목의 slug/id로 URL 추측 (사이트마다 패턴 다름 → 리스크)
    # 일단 base_url의 호스트 + /<slug> 추측
    if hydration_candidates and page_html:
        item = hydration_candidates[0].get("sample_first") or {}
        slug = item.get("slug") or item.get("id")
        if slug:
            # base_url의 path를 참고해 형제 경로 추측
            return urljoin(base_url, str(slug))
    # 3) JSON API 후보의 첫 항목 — 어댑터에서 정해야 하므로 None 반환
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
