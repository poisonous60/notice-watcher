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

from ._contract import validate_payload
from ._heuristic import heuristic
from .hydration import find_list_in_json


@heuristic
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
            # 자식 안의 a 태그 href — javascript:/#/빈값은 따로 분류(글 링크가 href 가 아니라 data-* / 인라인 JS 에 있음)
            hrefs: list[str] = []
            for child in group:
                a = child if child.name == "a" else child.find("a", href=True)
                if a and a.has_attr("href"):
                    hrefs.append(a["href"])
            real_hrefs = [h for h in hrefs if not _is_js_href(h)]
            href_is_js = bool(hrefs) and not real_hrefs   # 모든 href 가 javascript:/#/빈값
            common_prefix = _common_url_prefix(real_hrefs) if real_hrefs else None
            url_pattern = _href_pattern(real_hrefs) if real_hrefs else None
            first_text = " ".join((group[0].get_text(" ", strip=True) or "").split())[:120]
            sample_url = urljoin(base_url, real_hrefs[0]) if real_hrefs else None
            row_data_attrs = _row_data_attrs(group[0])

            selector = _css_selector(parent) + " > " + sig
            candidates.append({
                "selector": selector,
                "child_count": len(group),
                "first_text": first_text,
                "href_common_prefix": common_prefix,
                "href_pattern_guess": url_pattern,
                "sample_url": sample_url,
                "href_is_js": href_is_js or None,         # True → 글 링크가 javascript: — post_id/url 은 row_data_attrs / inline_js 에서. handwritten 어댑터 가능성.
                "row_data_attrs": row_data_attrs or None,  # 행 요소(와 그 안 첫 <a>)의 data-* 속성 샘플 (href 가 js 일 때 post_id 가 보통 여기)
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


@heuristic
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


@heuristic
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


@heuristic
def _href_pattern(hrefs: list[str]) -> Optional[str]:
    """첫 href에서 숫자/슬러그 부분을 placeholder로 치환한 추측 패턴."""
    if not hrefs:
        return None
    h = hrefs[0]
    # 쿼리스트링의 숫자 값과 path 끝의 숫자 segment를 {n}으로 치환
    h = re.sub(r"(=)\d+", r"\1{n}", h)
    h = re.sub(r"/\d+(/|$)", r"/{n}\1", h)
    return h


_JS_HREF_RE = re.compile(r"^\s*(?:#|javascript:)", re.IGNORECASE)


@heuristic
def _is_js_href(h: Optional[str]) -> bool:
    """href 가 글 URL 이 아닌 것 — 빈값, '#', 'javascript:...' (클릭 핸들러가 URL 을 만드는 목록)."""
    h = (h or "").strip()
    return (not h) or bool(_JS_HREF_RE.match(h))


@heuristic
def _row_data_attrs(tag: Tag, *, max_attrs: int = 8) -> dict:
    """행 요소(와 그 안 첫 <a>)의 data-* 속성 샘플. href 가 javascript: 인 목록에서 post_id 가 보통 여기 박혀 있다."""
    out: dict[str, str] = {}
    els: list[Tag] = [tag]
    try:
        a = tag.find("a")
    except Exception:  # noqa: BLE001
        a = None
    if isinstance(a, Tag) and a is not tag:
        els.append(a)
    for el in els:
        for k, v in (getattr(el, "attrs", {}) or {}).items():
            ks = str(k)
            if not ks.startswith("data-") or ks in out:
                continue
            sv = v if isinstance(v, str) else (" ".join(v) if isinstance(v, list) else str(v))
            out[ks] = sv[:80]
            if len(out) >= max_attrs:
                return out
    return out


# JSON API 후보 점수용 — 광고/트래커 도메인·경로(글 목록 API 가 아님) / 글 목록스러운 URL 경로 키워드.
_AD_TRACKER_RE = re.compile(
    r"(doubleclick|googlesyndication|googletagmanager|google-analytics|/gtag/|/gtm[./]|"
    r"\bpagead\b|adservice|adsystem|adnxs|criteo|taboola|outbrain|scorecardresearch|"
    r"amplitude|mixpanel|segment\.io|sentry|hotjar|clarity\.ms|onetag|/collect\b|/beacon|"
    r"/pixel|facebook\.com/tr|connect\.facebook|display\.ad\.|\bad\.daum\.|adlog\.|"
    r"/track(?:ing)?\b|/log(?:s|ging)?\b|/metric|/telemetry|/stat[s]?\b)", re.IGNORECASE,
)
_LIST_PATH_RE = re.compile(
    r"(feed|board|list|article|thread|notice|posts?|bbs|communit|content|news|bulletin|"
    r"gallery|topic|cafe|lounge|menus?|timeline)", re.IGNORECASE,
)
_DATEISH_KEY_RE = re.compile(r"(date|time|created|published|reg|updated|displayat|elapsed)", re.IGNORECASE)
_PAGING_PARAM_RE = re.compile(r"[?&](limit|offset|page|pageno|page_?size|page_?unit|page_?index|size|count|per_?page|start|rows)=", re.IGNORECASE)


def _entry_resource_type(entry: dict) -> str:
    return str(entry.get("_resourceType") or entry.get("resourceType") or "").lower()


@heuristic
def traffic_api_candidates(har_path: Path, *, page_url: str = "") -> list[dict]:
    """HAR 에서 '글 목록' 일 만한 JSON 응답 후보를 *관련도(relevance_score) 순* 으로.

    예전엔 5개 이상 배열을 가진 JSON 응답을 *발견 순서대로* 다 넣었다 — 그래서 광고 SDK/트래커 응답이 위에
    오거나(다음카페: 카카오 광고 배너 호출이 본문 API 로 오인됨), 진짜 목록 API 가 묻혀(네이버 게임 라운지
    `comm-api.game.naver.com/...feed`) Gemini 가 못 골랐다. 이제: 광고/트래커 도메인·경로 제외, 페이지와 다른
    사이트면 제외(page_url 알 때), XHR/fetch·URL 경로 키워드·항목 dict 의 날짜 키·항목 수·GET·200 으로 점수화해 정렬.

    응답 본문은 인라인 text / base64 / `record_har_content:"attach"` 의 외부 파일(`_file`) 셋 다 처리한다
    — headless 캡처는 attach 모드라 본문이 별도 .json 파일에 있어서, 안 그러면 큰 JSON API 가 전부 누락된다.
    """
    if not har_path.exists():
        return []
    try:
        har = json.loads(har_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return []

    from urllib.parse import urlsplit
    page_host = urlsplit(page_url).netloc if page_url else ""

    scored: list[tuple[int, dict]] = []
    for entry in (har.get("log", {}).get("entries", []) or []):
        req = entry.get("request", {}) or {}
        resp = entry.get("response", {}) or {}
        url = req.get("url") or ""
        if not url:
            continue
        if _AD_TRACKER_RE.search(url):
            continue                                  # 광고/트래커 — 글 목록 API 가 아님
        if page_url and not _same_site(url, page_url):
            continue                                  # 페이지와 다른 사이트 — 거의 글 목록이 아님
        ct = ""
        for h in resp.get("headers", []) or []:
            if str(h.get("name", "")).lower() == "content-type":
                ct = h.get("value", "") or ""
                break
        content = resp.get("content", {}) or {}
        looks_json = ("json" in ct.lower()
                      or "json" in str(content.get("mimeType", "")).lower()
                      or str(content.get("_file") or "").endswith(".json"))
        if not looks_json:
            continue
        text = _har_entry_response_text(entry, har_path)
        if not text:
            continue
        try:
            data = json.loads(text)
        except Exception:
            continue
        list_hits = find_list_in_json(data, min_items=5)
        if not list_hits:
            continue

        rtype = _entry_resource_type(entry)
        status = resp.get("status") or 0
        method = str(req.get("method") or "GET").upper()
        path = urlsplit(url).path or ""
        best_count = max((h.get("count") or 0) for h in list_hits)
        sample_keys = " ".join(str(k) for h in list_hits for k in (h.get("sample_keys") or []))
        score = 0
        if status == 200:
            score += 2
        elif status >= 400:
            score -= 3
        if rtype in ("xhr", "fetch"):
            score += 3
        elif rtype in ("document", "navigationpreload"):
            score -= 2
        if page_host and urlsplit(url).netloc == page_host:
            score += 1
        if _LIST_PATH_RE.search(path):
            score += 3                            # URL 경로에 feed/board/list/notice… — 글 목록 API 의 가장 강한 신호
        if method == "GET":
            score += 1
        score += min(2, best_count // 8)          # 8건+ → +1, 16건+ → +2 (게시판 목록은 보통 10~30건)
        if _DATEISH_KEY_RE.search(sample_keys):
            score += 1
        if _PAGING_PARAM_RE.search(url):
            score += 1                            # limit/offset/page… 쿼리 — 페이징 가능한 *목록* API 의 신호 (sticky pins API 와 구분됨)

        scored.append((score, {
            "method": req.get("method"),
            "url": url,
            "status": resp.get("status"),
            "content_type": ct,
            "resource_type": rtype or None,
            "relevance_score": score,
            "list_hits": list_hits,
            "request_headers": {str(h.get("name", "")): str(h.get("value", "")) for h in (req.get("headers") or [])},
            "request_body_text": (req.get("postData") or {}).get("text"),
        }))

    scored.sort(key=lambda t: t[0], reverse=True)
    return [c for _, c in scored]


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


@heuristic
def _ids_in_url(url: str) -> set[str]:
    """URL(경로+쿼리)에서 4자리 이상 숫자 런 — post_id 추정용."""
    from urllib.parse import urlsplit
    sp = urlsplit(url or "")
    return set(re.findall(r"\d{4,}", (sp.path or "") + "?" + (sp.query or "")))


_MULTI_TLD = ("co.kr", "co.jp", "co.uk", "com.cn", "or.kr", "ne.jp", "go.kr", "ac.kr")


@heuristic
def _registrable(host: str) -> str:
    """host → 등록가능도메인 근사치 (PSL 없이): co.kr/co.jp 등은 3라벨, 그 외 2라벨."""
    parts = (host or "").lower().split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in _MULTI_TLD:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else (host or "").lower()


@heuristic
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


@heuristic
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


@heuristic
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


@heuristic
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


@heuristic
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
    cand_urls = [c["sample_url"] for c in html_candidates if c.get("sample_url") and not c.get("href_is_js")]
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


@heuristic
def list_row_external_host(
    html_candidates: list[dict],
    *,
    base_url: str,
) -> Optional[dict]:
    """list row 후보들의 sample_url host 가 base_url host 와 다른 비율.

    검색결과 페이지(Google Scholar, 뉴스 aggregator 등)는 각 row 의 url 이 *외부 도메인*. 그런 페이지의
    article body 통합 추출은 불가 — config 작성자(LLM)가 이 신호를 보고 article 섹션을 생략하거나
    `article.skip_status:[200]` 으로 본문 fetch 시도 자체를 짧게 끊을 수 있다. validate.py 의 retry
    feedback 도 이 신호와 별개로 post.url host 직접 분석해 동일 hint 박음.

    필터: child_count ≥ 5 (의미 있는 반복 패턴) + sample_url 이 http(s) + sibling-page 패턴 제외
    (href_common_prefix 가 base_url 의 path 와 시작 일치 = pagination/sidebar 링크).

    출력: {base_host, total_count, external_count, external_ratio, sample_external_urls} 또는 None.
    None = 의미 있는 row 후보 0건.
    """
    from urllib.parse import urlsplit
    base_host = urlsplit(base_url or "").netloc
    if not base_host:
        return None
    base_path = (urlsplit(base_url or "").path or "/").rstrip("/") or "/"
    total = 0
    external = 0
    ext_samples: list[str] = []
    for c in html_candidates or []:
        if int(c.get("child_count") or 0) < 5:
            continue
        u = c.get("sample_url")
        if not u or not isinstance(u, str) or not u.startswith(("http://", "https://")):
            continue
        if c.get("href_is_js"):
            continue
        sp = urlsplit(u)
        if sp.netloc == base_host:
            href_prefix = str(c.get("href_common_prefix") or "")
            if href_prefix.startswith(base_path) or href_prefix.startswith("/scholar?") or href_prefix.startswith("?"):
                continue
            cand_path = (sp.path or "/").rstrip("/") or "/"
            if cand_path == base_path:
                continue
        total += 1
        if sp.netloc and sp.netloc != base_host:
            external += 1
            if len(ext_samples) < 5:
                ext_samples.append(u)
    if total == 0:
        return None
    return {
        "base_host": base_host,
        "total_count": total,
        "external_count": external,
        "external_ratio": round(external / total, 3),
        "sample_external_urls": ext_samples,
    }


# runtime_id_candidates: 사이트가 HTML 안에 *고정값으로 박아둔* ID/슬러그 후보.
# URL path 만으론 안 보이지만 (예: cafe.naver.com/<slug> 는 cafe_id 가 없음) 페이지 HTML 안에 박혀
# 있는 ID — `g_sClubId="31104609"`, `<meta property="og:url" content=".../boards/1018">`,
# `__NEXT_DATA__.props.pageProps.boardId` 등. config 작성자(LLM·사람·recognizer 후처리)가
# 그 ID 를 보고 url_template / kwargs / handwritten adapter 의 매개변수를 *고정값* 으로 박을 수 있다.
# (어댑터가 매 polling 마다 fetch+scrape 안 해도 됨.)

_ID_VAR_NAME_RE = re.compile(
    r"\b(?P<name>(?:g_s|window\.)?"
    r"(?:club|cafe|board|menu|lounge|forum|community|channel|gallery|site|page|category|topic|thread|article|post|user|tenant|workspace|space)"
    r"(?:Id|_id|ID|_ID))\b",
    re.IGNORECASE,
)
_ID_VAR_ASSIGN_RE = re.compile(
    # `var foo = "123"` / `foo = 123` / `"foo": "123"` / `"foo": 123`
    r"""
    (?:var\s+|let\s+|const\s+|window\.|"\s*)?
    (?P<name>(?:g_s|window\.)?
        (?:club|cafe|board|menu|lounge|forum|community|channel|gallery|site|page|category|topic|thread|article|post|tenant|workspace|space)
        (?:Id|_id|ID|_ID)
    )
    \s*["']?\s*[=:]\s*
    ["']?(?P<value>[A-Za-z0-9_-]{1,64})["']?
    """,
    re.IGNORECASE | re.VERBOSE,
)
_ID_INT_RE = re.compile(r"^\d{2,}$")  # 단일 자리 0~9 는 의미 없음 — id 후보로 제외.


@heuristic
def runtime_id_candidates(html: str, *, max_per_source: int = 20) -> list[dict]:
    """페이지 HTML 안 *런타임 ID/슬러그* 후보 추출.

    출력 dict: {name:str, value:str, source:"js_var"|"next_data"|"meta_og_url"|"hydration_path", context:str}

    소스별:
      - js_var: `g_sClubId = "31104609"`, `var boardId = 1018` 같은 JS var 할당. name 화이트리스트
        (board/cafe/club/lounge/forum/... + Id 접미) — 임의 변수까지 잡으면 노이즈 많음.
      - next_data: `__NEXT_DATA__` 의 JSON 안에서 이름이 `*Id`/`*_id` 로 끝나는 키 + 정수/짧은 문자열 값.
      - meta_og_url: `<meta property="og:url">` URL path 끝 segment (정수만).

    *추측이 아니라 직접 박힌 값만* 반환 — 사이트가 페이지에 명시한 fact. config 작성자가 이걸 보고
    `kwargs.cafe_id=31104609`, `url_template=.../boards/1018/...` 처럼 *고정값* 으로 박는 게 목적.
    """
    if not html:
        return []
    out: list[dict] = []

    soup = BeautifulSoup(html, "lxml")

    # 1. js_var
    seen_js: set[tuple[str, str]] = set()
    js_count = 0
    for m in _ID_VAR_ASSIGN_RE.finditer(html):
        if js_count >= max_per_source:
            break
        name = m.group("name")
        value = m.group("value")
        # name 자체가 식별자 패턴인지 다시 검증 (_ID_VAR_ASSIGN_RE 안 alternation 만으로는 부분일치 가능)
        if not _ID_VAR_NAME_RE.fullmatch(name):
            continue
        # value 가 *literal* 인지 *다른 식별자 이름* 인지 구분.
        # ID 후보로 받는 형태:
        #   - 순수 정수 (2자리 이상): "31104609", "1018"
        #   - 숫자가 포함된 슬러그: "abc-123", "ab_42"
        #   - 하이픈 포함 슬러그: "uuid-style-thing"
        # 거부:
        #   - 순수 letter camelCase 식별자: "target", "liTarget", "cafeId" — 보통 JS 변수 참조 (값 아님)
        is_pure_int = value.isdigit() and len(value) >= 2
        is_slug_with_digit_or_dash = (
            len(value) >= 2
            and re.fullmatch(r"[A-Za-z0-9_-]+", value) is not None
            and (any(ch.isdigit() for ch in value) or "-" in value)
        )
        if not (is_pure_int or is_slug_with_digit_or_dash):
            continue
        key = (name, value)
        if key in seen_js:
            continue
        seen_js.add(key)
        ctx_start = max(0, m.start() - 20)
        ctx_end = min(len(html), m.end() + 20)
        out.append({
            "name": name,
            "value": value,
            "source": "js_var",
            "context": html[ctx_start:ctx_end].replace("\n", " ").strip()[:120],
        })
        js_count += 1

    # 2. next_data
    next_data_tag = soup.find("script", id="__NEXT_DATA__")
    if isinstance(next_data_tag, Tag):
        try:
            data = json.loads(next_data_tag.string or "")
        except (json.JSONDecodeError, TypeError):
            data = None
        if isinstance(data, (dict, list)):
            count = 0
            for path, value in _walk_id_keys(data):
                if count >= max_per_source:
                    break
                out.append({
                    "name": path,
                    "value": str(value),
                    "source": "next_data",
                    "context": ".".join(path.split(".")[-3:]),
                })
                count += 1

    # 3. meta_og_url — bs4 로 attribute 순서 무관하게 찾음 (regex 가 property→content 순서만 잡으면 silent miss).
    og_tag = soup.find("meta", attrs={"property": "og:url"})
    if isinstance(og_tag, Tag):
        og_url = og_tag.get("content")
        if isinstance(og_url, str) and og_url:
            from urllib.parse import urlsplit
            sp = urlsplit(og_url)
            segs = [s for s in sp.path.split("/") if s]
            if segs and _ID_INT_RE.fullmatch(segs[-1]):
                out.append({
                    "name": "og:url last segment",
                    "value": segs[-1],
                    "source": "meta_og_url",
                    "context": og_url[:120],
                })

    return out


def _walk_id_keys(node, prefix: str = "", _depth: int = 0):
    """__NEXT_DATA__ JSON 안 *Id/_id 키 + scalar 값 (정수 또는 짧은 슬러그) 만 yield. 최대 depth 6."""
    if _depth > 6:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            new_prefix = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, (str, int)) and re.search(r"(Id|_id|ID|_ID)$", str(k)):
                sv = str(v)
                if _ID_INT_RE.fullmatch(sv) or (len(sv) >= 2 and len(sv) <= 64
                                                and re.fullmatch(r"[A-Za-z0-9_-]+", sv)):
                    yield new_prefix, v
            elif isinstance(v, (dict, list)):
                yield from _walk_id_keys(v, new_prefix, _depth + 1)
    elif isinstance(node, list):
        for i, v in enumerate(node[:20]):  # list 는 첫 20 까지만
            if isinstance(v, (dict, list)):
                yield from _walk_id_keys(v, f"{prefix}[{i}]", _depth + 1)


def write_list_candidates(
    out_dir: Path,
    *,
    html_candidates: list[dict],
    json_api_candidates: list[dict],
    hydration_candidates: list[dict],
    first_article_url: Optional[str],
    inline_js_candidates: Optional[list[dict]] = None,
    runtime_ids: Optional[list[dict]] = None,
    row_external_host: Optional[dict] = None,
) -> None:
    payload = {
        "html_repeating_patterns": html_candidates,
        "traffic_json_api_candidates": [
            {k: v for k, v in c.items() if k != "request_body_text"} for c in json_api_candidates
        ],
        "hydration_list_candidates": hydration_candidates,
        # 목록이 정적 HTML 행이 아니라 인라인 JS/JSON 안에 있을 때 (다음카페 모바일: articles.push({...}) 등). probe/hydration.extract_inline_data 산출.
        "inline_js_data_candidates": inline_js_candidates or [],
        # 페이지 HTML 안에 박힌 ID/슬러그 후보 — URL 에 없지만 사이트가 명시한 cafe_id/board_id 등.
        "runtime_id_candidates": runtime_ids or [],
        "first_article_url": first_article_url,
        # list row 들의 sample_url host 가 base host 와 다른 비율 — 검색결과/aggregator 검출.
        # None = 의미 있는 row 후보 0건; dict = {base_host, total_count, external_count, external_ratio, sample_external_urls}.
        "row_external_host": row_external_host,
    }
    validate_payload("list_candidates.json", payload, allow_extra=False)
    (out_dir / "list_candidates.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
