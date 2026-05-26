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
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from ._contract import validate_payload
from ._heuristic import heuristic
from .hydration import find_list_in_json

try:
    import tldextract as _tldextract
except ImportError:  # pragma: no cover — tldextract 가 requirements 에 있음. 없는 환경 fallback.
    _tldextract = None


def _registered_domain(host: str) -> str:
    """host (netloc) → registered domain (etld+1) 소문자.

    `m.dcinside.com`/`gall.dcinside.com` → `dcinside.com` (sibling subdomain 같은 사이트로 묶음).
    `www.example.co.kr` → `example.co.kr` (3-segment public suffix 정확 처리 — tldextract 사용).

    tldextract 없으면 last-2-segments fallback (부정확하지만 동작).
    """
    if not host:
        return ""
    h = host.lower().split(":", 1)[0]  # port 제거
    if _tldextract is not None:
        try:
            ex = _tldextract.extract(h)
            if ex.domain and ex.suffix:
                return f"{ex.domain}.{ex.suffix}"
        except Exception:
            pass
    # fallback — 2-segment (.co.kr 같은 public suffix 는 부정확하지만 대부분 OK)
    parts = h.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return h


_SKELETON_DESCENDANT_TOKEN_RE = re.compile(
    r"(?<!\w)(skeleton|p-skeleton|loading|loading-spinner|placeholder|shimmer|spinner|ghost|empty-state)(?!\w)",
    re.IGNORECASE,
)


def _row_has_skeleton_descendant(row: "Tag", *, max_desc: int = 10) -> bool:
    """row 의 descendant element class 에 skeleton/loading/placeholder 등 박혀있는지.

    Radiolab 류 — row sig (`div.col-12.mb-6`) 자체엔 skeleton 없지만 descendant 의
    `<div class="p-skeleton p-component card">` 가 박힘. html_repeating_patterns 의 top
    후보로 잡히면 LLM 함정. row 의 첫 N 자손 element class 검사 후 reject 신호.

    2026-05-25 codex review (parent + child sig 만 봄 → descendant 안 봄) 정정.
    """
    try:
        descendants = list(row.find_all(True))[:max_desc]
    except Exception:
        return False
    for el in descendants:
        try:
            cls_list = el.get("class") or []
        except Exception:
            continue
        if not isinstance(cls_list, list):
            continue
        for cls in cls_list:
            if not isinstance(cls, str):
                continue
            if _SKELETON_DESCENDANT_TOKEN_RE.search(cls):
                return True
    return False


@heuristic
def html_repeating_patterns(html: str, base_url: str, *, min_children: int = 5) -> list[dict]:
    """같은 부모 안에서 같은 시그니처(태그+클래스)를 갖는 자식이 N개 이상인 노드 후보."""
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    candidates: list[dict] = []
    js_detail_templates = extract_js_detail_template(html, base_url=base_url)

    for parent in soup.find_all(True):
        if not isinstance(parent, Tag):
            continue
        children = [c for c in parent.find_all(recursive=False) if isinstance(c, Tag)]
        if len(children) < min_children:
            continue
        if str(parent.name).lower() == "head":
            continue
        # 시그니처 그룹핑
        groups: dict[str, list[Tag]] = {}
        for c in children:
            sig = _signature(c)
            groups.setdefault(sig, []).append(c)
        for sig, group in groups.items():
            if len(group) < min_children:
                continue
            if str(group[0].name).lower() in {"script", "style", "meta", "link"}:
                continue
            # skeleton descendant reject — group 의 sample (group[0]) 안 자손 class 에
            # skeleton/loading/placeholder 있으면 SPA hydration 전 캡처된 가짜 row.
            # LLM 함정 회피 — 후보 list 에서 제외.
            if _row_has_skeleton_descendant(group[0]):
                continue
            # 자식 안의 a 태그 href — javascript:/#/빈값은 따로 분류(글 링크가 href 가 아니라 data-* / 인라인 JS 에 있음)
            hrefs: list[str] = []
            base_host = urlsplit(base_url or "").netloc
            for child in group:
                if child.name == "a" and child.has_attr("href"):
                    anchors = [child]
                else:
                    anchors = list(child.find_all("a", href=True))
                if anchors:
                    hrefs.append(_best_row_href(anchors, base_url, base_host))
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
                "detail_url_template": _match_js_detail_template(hrefs, js_detail_templates),
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


_JS_CALL_RE = re.compile(
    r"(?:javascript:\s*)?([A-Za-z_$][\w$]*)\s*\(\s*['\"]?([A-Za-z0-9_-]+)['\"]?",
    re.IGNORECASE,
)
_FUNC_BODY_RE = re.compile(
    r"function\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)\s*\{(?P<body>.*?)\}",
    re.IGNORECASE | re.DOTALL,
)
_LOCATION_EXPR_RE = re.compile(
    r"(?:location(?:\.href)?|window\.location(?:\.href)?|document\.location)\s*=\s*(?P<expr>[^;]+)",
    re.IGNORECASE | re.DOTALL,
)


def _js_string_value(token: str) -> Optional[str]:
    token = token.strip()
    if len(token) >= 2 and token[0] in ("'", '"') and token[-1] == token[0]:
        return token[1:-1]
    return None


def _template_from_js_expr(expr: str, param_name: str) -> Optional[str]:
    parts = [p.strip() for p in expr.split("+")]
    if len(parts) < 2:
        return None
    out = ""
    used_param = False
    for part in parts:
        sv = _js_string_value(part)
        if sv is not None:
            out += sv
            continue
        if part == param_name or part.endswith("." + param_name):
            out += "{post_id}"
            used_param = True
            continue
        return None
    return out if used_param else None


def _js_calls_from_attrs(soup: BeautifulSoup) -> list[dict]:
    calls: list[dict] = []
    for el in soup.find_all(True):
        if not isinstance(el, Tag):
            continue
        for attr in ("href", "onclick"):
            raw = el.get(attr)
            if not isinstance(raw, str):
                continue
            m = _JS_CALL_RE.search(raw)
            if not m:
                continue
            calls.append({"function": m.group(1), "sample_id": m.group(2), "raw": raw})
    return calls


@heuristic
def extract_js_detail_template(html: str, *, base_url: str) -> list[dict]:
    """Inline JS `goView(id)`/`goDetailPage(no)` 함수에서 상세 URL template 추출.

    지원 범위는 보수적으로 `location.href = '/path?id=' + id + '&x=1'` 형태만이다.
    복잡한 조건문/폼 submit 은 handwritten 영역으로 남긴다.
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    calls = _js_calls_from_attrs(soup)
    if not calls:
        return []
    wanted = {c["function"] for c in calls}
    first_id: dict[str, str] = {}
    for c in calls:
        first_id.setdefault(c["function"], c["sample_id"])
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for fm in _FUNC_BODY_RE.finditer(html):
        fname = fm.group(1)
        if fname not in wanted:
            continue
        params = [p.strip() for p in fm.group(2).split(",") if p.strip()]
        if not params:
            continue
        loc = _LOCATION_EXPR_RE.search(fm.group("body") or "")
        if not loc:
            continue
        tmpl = _template_from_js_expr(loc.group("expr"), params[0])
        if not tmpl:
            continue
        abs_tmpl = urljoin(base_url, tmpl)
        key = (fname, abs_tmpl)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "function": fname,
            "sample_id": first_id.get(fname),
            "detail_url_template": abs_tmpl,
        })
    return out


def _match_js_detail_template(hrefs: list[str], templates: list[dict]) -> Optional[str]:
    if not hrefs or not templates:
        return None
    funcs = set()
    for href in hrefs:
        m = _JS_CALL_RE.search(href or "")
        if m:
            funcs.add(m.group(1))
    for t in templates:
        if t.get("function") in funcs:
            return t.get("detail_url_template")
    return None


_AUTH_REDIRECT_RE = re.compile(r"(권한|인증|로그인|permission|auth|unauthori[sz]ed|alert\s*\()", re.IGNORECASE)
_EMPTY_SHELL_RE = re.compile(r"(게시판을\s*선택|메뉴를\s*선택|목록이\s*없|등록된\s*게시물이\s*없|no\s+data|no\s+posts)", re.IGNORECASE)
_MENU_PARAM_NAMES = ("menuid", "menuId", "menuCd", "mId", "mid", "mnSeq")
_BOARD_PARAM_NAMES = ("bbsId", "boardId", "boardtypeid", "bid")


def _query_params(url: str) -> dict[str, str]:
    return {k: v for k, v in parse_qsl(urlsplit(url).query, keep_blank_values=True)}


def _same_url_family(base_url: str, href: str) -> bool:
    b = urlsplit(base_url)
    h = urlsplit(urljoin(base_url, href))
    if b.netloc and h.netloc and b.netloc != h.netloc:
        return False
    if b.path and h.path and b.path.rstrip("/") != h.path.rstrip("/"):
        return False
    bq = _query_params(base_url)
    hq = _query_params(urlunsplit((h.scheme, h.netloc, h.path, h.query, "")))
    shared_board = [k for k in _BOARD_PARAM_NAMES if k in bq and hq.get(k) == bq[k]]
    return bool(shared_board)


@heuristic
def detect_url_missing_param_pattern(
    html: str,
    *,
    base_url: str,
    html_candidates: list[dict],
) -> Optional[dict]:
    """KR egov board URLs that need menu/mid params in addition to board id.

    The signal is deliberately diagnostic only: current URL has a board id but lacks a menu-ish
    param, page looks like an auth redirect/empty shell/empty rows, and same-family links expose
    that missing param.
    """
    if not html or not base_url:
        return None
    base_params = _query_params(base_url)
    if not any(k in base_params for k in _BOARD_PARAM_NAMES):
        return None
    if any(k in base_params for k in _MENU_PARAM_NAMES):
        return None
    if html_candidates:
        rowish = [c for c in html_candidates if c.get("sample_url") and int(c.get("child_count") or 0) >= 3]
        if rowish:
            return None

    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    symptom: Optional[str] = None
    if _AUTH_REDIRECT_RE.search(html):
        symptom = "auth_redirect"
    elif _EMPTY_SHELL_RE.search(text):
        symptom = "empty_shell"
    else:
        trs = len(re.findall(r"<tr\b", html, re.IGNORECASE))
        anchors = len(re.findall(r"<a\b", html, re.IGNORECASE))
        if trs <= 1 and anchors >= 1:
            symptom = "empty_rows"
    if symptom is None:
        return None

    soup = BeautifulSoup(html, "lxml")
    candidates: list[dict] = []
    counts: dict[str, int] = {}
    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "")
        if not _same_url_family(base_url, href):
            continue
        full = urljoin(base_url, href)
        params = _query_params(full)
        for name in _MENU_PARAM_NAMES:
            if name in params and name not in base_params:
                counts[name] = counts.get(name, 0) + 1
                candidates.append({"url": full, "param": name, "value": params.get(name)})
    if not counts:
        return None
    suggested = sorted(counts.items(), key=lambda kv: (-kv[1], _MENU_PARAM_NAMES.index(kv[0])))[0][0]
    return {
        "symptom": symptom,
        "suggested_param": suggested,
        "candidates": [c for c in candidates if c["param"] == suggested][:5],
    }


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


def _best_row_href(anchors: list[Tag], base_url: str, base_host: str) -> str:
    """반복 row 안 링크가 여럿이면 카테고리/태그보다 글 URL 같은 href 를 고른다."""
    best = anchors[0].get("href") or ""
    best_score = _article_url_score(urljoin(base_url, best), base_host) if not _is_js_href(best) else -1
    for a in anchors[1:]:
        href = a.get("href") or ""
        score = _article_url_score(urljoin(base_url, href), base_host) if not _is_js_href(href) else -1
        if score > best_score:
            best = href
            best_score = score
    return best


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


def _json_url_source_script_hints(har: dict, har_path: Path, *, json_url: str, page_url: str = "") -> list[dict]:
    """Best-effort: find which same-site JS response appears to construct a JSON URL.

    HAR does not always expose request initiators. For JS-built monthly APIs, the
    observed JSON URL may not appear literally in HTML, but the script often has
    the stable prefix/suffix (`news_` + month + `.json`). This is diagnostic
    evidence for the config writer, not an engine template.
    """
    from urllib.parse import urlsplit

    path = urlsplit(json_url or "").path
    name = path.rsplit("/", 1)[-1]
    if not name:
        return []
    m = re.match(r"(?P<prefix>[^/?#]*?)(?P<num>\d{4,})(?P<suffix>\.[A-Za-z0-9]+)$", name)
    prefix = m.group("prefix") if m else ""
    suffix = m.group("suffix") if m else ""

    out: list[dict] = []
    for entry in (har.get("log", {}).get("entries", []) or []):
        req = entry.get("request", {}) or {}
        resp = entry.get("response", {}) or {}
        script_url = req.get("url") or ""
        if not script_url:
            continue
        if page_url and not _same_site(script_url, page_url):
            continue
        ct = ""
        for h in resp.get("headers", []) or []:
            if str(h.get("name", "")).lower() == "content-type":
                ct = h.get("value", "") or ""
                break
        if "javascript" not in ct.lower() and not urlsplit(script_url).path.lower().endswith(".js"):
            continue
        text = _har_entry_response_text(entry, har_path)
        if not text:
            continue
        evidence = None
        idx = text.find(name)
        if idx >= 0 and (len(name) >= 8 or "." in name):
            evidence = name
        elif prefix and suffix:
            idx = text.find(prefix)
            if idx >= 0 and suffix in text[idx: idx + 240]:
                evidence = text[idx: idx + 240].replace("\n", " ")[:180]
        if evidence:
            out.append({"script_url": script_url, "evidence": evidence})
            if len(out) >= 2:
                break
    return out


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
            "source_script_hints": _json_url_source_script_hints(har, har_path, json_url=url, page_url=page_url),
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
    """'진짜 글 페이지 URL' 같은 정도. (헤더의 myinfo/login 링크 같은 잡 후보를 거르기 위해)

    페널티 (2026-05-17 추가):
      - query string 안 sort/filter/search/keyword/q= 류 패턴 → -3 (글 페이지가 아니라 *검색·필터 결과 페이지*).
        humblebundle `/store/search?sort=bestselling&filter=onsale` 같은 헤더의 "Browse Store" 류를 거른다.
      - path-only 깨끗한 URL (`/path/machine-name` 패턴, 숫자 ID 없이도 안정) → +1
    누적 4건 (humblebundle/nexon/jobplanet/nature) — `cases_index.py query --signal diverging_first_article` 확인.
    """
    if not u:
        return -1
    from urllib.parse import urlsplit
    sp = urlsplit(u)
    s = 0
    if base_host and _registrable(sp.netloc) == _registrable(base_host):
        s += 4                                    # 같은 사이트 (www/non-www 차이는 같은 사이트로 봄)
    if sp.path and sp.path not in ("", "/"):
        s += 1
    if re.search(r"\d{3,}", (sp.path or "") + "?" + (sp.query or "")):
        s += 2                                    # 글 ID 같은 숫자
    if re.search(r"(view|detail|article|notice|read|thread|post|bbs|board)", (sp.path or "").lower()):
        s += 1
    # 페널티: query string 의 검색/필터/정렬 파라미터 — 글 페이지 아님
    q = (sp.query or "").lower()
    if q and re.search(r"(?:^|&)(sort|filter|search|keyword|query|q|page|category)=", q):
        s -= 3
    # 페널티: path 가 검색·목록 엔드포인트
    path_l = (sp.path or "").lower()
    if re.search(r"/(search|list|index|all|category|tag|sort|filter)(?:/|$|\?)", path_l):
        s -= 2
    # 페널티: 프로필/유저 페이지 — 글 본문이 아님. XenForo `/members/<slug>.<id>/` 가 thread
    #   `/threads/<slug>.<id>/` 와 같은 모양이라 same_host+id 로 동률(둘 다 7~8) → first_article 로 오인
    #   (avsforum members/eevblog ?u= 누적, 2026-05-21-forums batch). -3 으로 글 후보에서 밀어낸다.
    if re.search(r"/(members?|profiles?|users?)(?:/|$)", path_l):
        s -= 3
    if re.search(r"(?:^|&)(u|user|userid|member)=", q):
        s -= 3
    # 페널티: 카테고리/서브포럼 listing — forums/boards 복수형, 또는 board/forum/node/category 뒤 bare 숫자 id
    #   (XenForo `/forums/<slug>.<id>/`, fredmiranda `/forum/board/41/`, hardforum). 글 목록이지 글이 아님.
    if (re.search(r"/(forums|boards|categories)(?:/|$)", path_l)
            or re.search(r"/(board|forum|node|category)/\d+/?$", path_l)):
        s -= 2
    # 페널티: archive(s) 또는 `<word>_list` 류 endpoint — 날짜/월 archive 페이지 또는 다른 board 목록 링크.
    #   누적 3건 (2026-05-26 mobius `/news/archives/MM-YYYY` 글 6점 vs archive 8점으로 졌음 + 2026-05-21
    #   comic-days `/info/archive/YYYY/MM/DD` first_article 오인 + 2026-05-11 nexon-bluearchive sidebar
    #   `/bluearchive/board_list?board=1618` 다른 board 목록 → first_article 오인). _list ending 은
    #   기존 `/list/` slash 형태가 못 잡는 `board_list`/`news_list` 류를 잡는다. -3 = `/search` 류와 동일
    #   강도 (archive path 의 date segment `/06-2025` 가 machine-name 보너스 +1 을 받아 -2 로는 동률만
    #   되니 -3 필요).
    if re.search(r"/archives?(?:/|$)", path_l):
        s -= 3
    if re.search(r"/[a-z]+_list(?:/|$|\?)", path_l):
        s -= 3
    # 보너스: path-only 깨끗한 URL (machine-name 패턴, query 없음)
    if not sp.query and re.search(r"/[a-z0-9][a-z0-9_\-]{4,}/?$", path_l):
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


# 본문이 본질적으로 없는 사이트 — row 의 first_text 안 *액션 UI* 키워드 매칭.
# 게임 디렉토리 (이상형월드컵 piku) / 투표·설문 / 인터랙티브 SPA 검출. KO/EN 액션 단어.
# 짧고 보수적인 사전 — false positive 위험 줄이려 *합성어/명사구* 위주 (단어 "play"/"start" 단독 X).
_INTERACTIVE_ACTION_KEYWORDS: tuple[str, ...] = (
    # KO 게임 UI / 월드컵
    "이상형월드컵", "이상형 월드컵", "월드컵", "시작하기", "랭킹보기",
    "투표하기", "참여하기", "결과보기", "라운드", "준결승", "결승전",
    # KO 인터랙티브
    "좋아요", "싫어요", "공유하기",
    # EN 게임/투표
    "Vote now", "Start game", "Play now", "Round 1", "winner takes",
    "tournament", "bracket",
)


@heuristic
def list_row_interactive_action_text(
    html_candidates: list[dict],
) -> Optional[dict]:
    """list row 의 `first_text` 안 *액션 UI* 키워드 매칭 — 본문 없는 사이트 (게임 디렉토리 / 투표·설문 / 인터랙티브 SPA) 검출.

    검출 룰:
      - 후보 row: `child_count ≥ 5` 인 `html_repeating_patterns` 항목
      - 매칭 row: `first_text` 안 `_INTERACTIVE_ACTION_KEYWORDS` 중 **≥2개** 등장
      - 의미 있는 신호: matched_row_count ≥ 1 + matched_keyword 종류 ≥ 2 (단어 한 종이 우연히 들어간 케이스 배제)

    *왜 보수적인가*: row 안에 "play"/"start" 같은 흔한 단어 단독은 정상 게시판 (게임 카페 등) 도 매칭됨.
    "이상형월드컵"/"라운드"/"Vote now" 같은 *합성어/구* 만 키워드로 — false positive 줄임.

    출력: {matched_row_count, matched_keyword_set, sample_row_first_text, is_interactive_action: bool}
        또는 None — 매칭 0건 또는 의미 있는 신호 미달.
    """
    if not html_candidates:
        return None
    matched_rows: list[tuple[str, set[str]]] = []
    for c in html_candidates:
        if int(c.get("child_count") or 0) < 5:
            continue
        ft = str(c.get("first_text") or "")
        if not ft:
            continue
        hits = {kw for kw in _INTERACTIVE_ACTION_KEYWORDS if kw in ft}
        if len(hits) >= 2:
            matched_rows.append((ft[:120], hits))
    if not matched_rows:
        return None
    # 매칭 row 들의 키워드 union (의미: 사이트 전체 패턴인지 확인)
    all_keywords: set[str] = set()
    for _ft, kws in matched_rows:
        all_keywords |= kws
    return {
        "matched_row_count": len(matched_rows),
        "matched_keyword_set": sorted(all_keywords),
        "sample_row_first_text": matched_rows[0][0],
        "is_interactive_action": True,
    }


@heuristic
def static_vs_headless_check(
    static_html: Optional[str],
    headless_html: Optional[str],
    *,
    min_ratio: float = 2.0,
    min_row_diff: int = 5,
    base_url: Optional[str] = None,
) -> dict:
    """정적 응답 vs Playwright 응답 콘텐츠 비교 — *정적이 충분한지* 검증.

    검출 룰 (둘 중 하나 True 면 `static_insufficient=True`):
      1. **size + row-signal**: `headless_size / static_size ≥ min_ratio` AND
         headless 의 row-like 신호 (`data-id=`/`<a ` count) 가 정적보다 `+ min_row_diff` 이상
      2. **반복 패턴 anchor count diff** (2026-05-17 추가, base_url 필요): 같은 class
         signature 의 sibling 그룹 anchor 가 globally 정적 0 / headless ≥ 10 (즉, JS 가
         tile/card 를 0→N 으로 그림). humblebundle 처럼 size ratio 작아도 (1.25배)
         반복 패턴 anchor 가 0→22 인 경우 잡힘.

    *왜 필요한가*: probe 의 verdict 결정이 HTTP status(200 OK) 만 보고 "정적 HTTP로 충분" 박음.
    piku 같은 사이트 (정적 14kb data-id=0 vs Playwright 44kb data-id=20) 도 같은 weight 로
    봐서 LLM 한테 잘못된 strategy=httpx_html 권고 → retry 헛수고. 룰 1 이 그걸 잡음.
    humblebundle 처럼 헤더/푸터/스크립트가 정적·headless 동일이라 size ratio 가 1.25 머무는데
    번들 타일만 JS render (0→22) 인 케이스는 룰 1 이 못 잡음 — 룰 2 가 그걸 잡음.

    출력: {static_size, headless_size, ratio, row_signal_static, row_signal_headless,
           repeat_anchors_static, repeat_anchors_headless, repeat_anchors_diff,
           static_insufficient: bool, trigger_rule: "size"|"repeat"|None}
        둘 중 하나라도 None/빈 문자열이면 ratio=0.0 / static_insufficient=False (판단 불가 → 안전쪽).
    """
    s_text = static_html or ""
    h_text = headless_html or ""
    s_size = len(s_text)
    h_size = len(h_text)
    if s_size == 0 or h_size == 0:
        return {
            "static_size": s_size, "headless_size": h_size,
            "ratio": 0.0,
            "row_signal_static": 0, "row_signal_headless": 0,
            "repeat_anchors_static": 0, "repeat_anchors_headless": 0,
            "repeat_anchors_diff": 0,
            "static_insufficient": False,
            "trigger_rule": None,
        }
    s_signal = s_text.count("data-id=") + s_text.count("<a ")
    h_signal = h_text.count("data-id=") + h_text.count("<a ")
    ratio = round(h_size / s_size, 2)
    rule1 = (ratio >= min_ratio) and ((h_signal - s_signal) >= min_row_diff)

    # 룰 2: 반복 패턴 selector-level diff — *headless 에만 등장* 또는 *headless 가 정적 3배 이상* 인 selector 들의
    # child_count 합 ≥ 10 → drift. nav/footer 같은 양쪽 동일 패턴은 빠지고 *JS render 로 새로 생긴* tile/card 만 잡힘.
    # base_url 필요 (selector 생성 시).
    s_repeat = h_repeat = 0
    if base_url:
        try:
            s_patterns = html_repeating_patterns(s_text, base_url=base_url, min_children=3)
            h_patterns = html_repeating_patterns(h_text, base_url=base_url, min_children=3)
            s_sels = {p["selector"]: int(p.get("child_count") or 0) for p in s_patterns}
            h_sels = {p["selector"]: int(p.get("child_count") or 0) for p in h_patterns}
            # selector-by-selector: headless 가 정적보다 *유의미하게* 더 그린 만큼만 카운트.
            #   - 정적 0 / headless ≥ N      → headless count
            #   - 정적 N / headless ≥ 3N    → headless - static
            #   - 외엔 0 (nav/footer 등 양쪽 비슷)
            for sel, h_cc in h_sels.items():
                s_cc = s_sels.get(sel, 0)
                if s_cc == 0 and h_cc >= 3:
                    h_repeat += h_cc
                elif h_cc >= s_cc * 3 and h_cc - s_cc >= 5:
                    h_repeat += h_cc - s_cc
            # s_repeat = headless-only-or-3x 신호의 정적 baseline (참고용)
            for sel, s_cc in s_sels.items():
                if sel in h_sels and h_sels[sel] >= s_cc:
                    s_repeat += s_cc
        except Exception:
            s_repeat = h_repeat = 0
    repeat_diff = h_repeat  # headless 가 새로 그린 양
    rule2 = h_repeat >= 20  # 임계 20 — humblebundle(51)/itch.io(46)/jobplanet(79) 통과, naver-blog post(41) 도 잡히지만 무해(검토)

    static_insufficient = rule1 or rule2
    trigger = "size" if rule1 else ("repeat" if rule2 else None)
    return {
        "static_size": s_size,
        "headless_size": h_size,
        "ratio": ratio,
        "row_signal_static": s_signal,
        "row_signal_headless": h_signal,
        "repeat_anchors_static": s_repeat,
        "repeat_anchors_headless": h_repeat,
        "repeat_anchors_diff": repeat_diff,
        "static_insufficient": static_insufficient,
        "trigger_rule": trigger,
    }


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

    output: {base_host, base_registered_domain, total_count, external_count, external_ratio,
             sample_external_urls, unique_external_hosts, multi_host_hub} 또는 None.
    None = 의미 있는 row 후보 0건.

    multi_host_hub: True 면 *플랫폼 hub root* — `unique_external_hosts ≥ 3 AND external_ratio ≥ 0.95`
    AND (외부 호스트들이 base 와 *다른* etld+1 를 *하나라도* 포함). tistory root (3+ unique blog
    호스트 *.tistory.com + daum.net 같이 다른 etld+1 섞임) / 기사 aggregator hub 패턴. 단일 sponsor
    link (poly-pizza total=1) / single wiki mirror (github-wiki-see external_count=1) false-positive
    안 잡힘.

    sibling subdomain (2026-05-20 fix): 모든 외부 host 가 base 와 *같은* etld+1 면 sibling subdomain —
    `m.dcinside.com` ↔ `gall.dcinside.com`/`www.dcinside.com` 같은 인프라 분리. multi_host_hub=False.
    (이전엔 m.dcinside/board/maple 이 gall.dcinside.com row URL 로 false-positive multi_host_hub.)
    base 와 같은 etld+1 의 sibling subdomain 은 여전히 external 카운트에는 들어감 (ratio 계산용) —
    *multi_host_hub flag* 만 끔. 검색결과/aggregator 패턴 (`external_ratio≥0.8` 신호) 은 그대로 유지.

    register.py 가 multi_host_hub 신호 보면 사전 REJECTED 마커 (인식기 fast-path 없는 새 hub 호스트
    자동 cover).
    """
    from urllib.parse import urlsplit
    base_host = urlsplit(base_url or "").netloc
    if not base_host:
        return None
    base_path = (urlsplit(base_url or "").path or "/").rstrip("/") or "/"
    base_reg = _registered_domain(base_host)
    total = 0
    external = 0
    ext_samples: list[str] = []
    ext_hosts: set[str] = set()
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
            ext_hosts.add(sp.netloc)
            if len(ext_samples) < 5:
                ext_samples.append(u)
    if total == 0:
        return None
    ratio = round(external / total, 3)
    # sibling subdomain 가드 — 모든 외부 호스트가 base 와 같은 etld+1 면 hub 아님 (m.dcinside ↔ gall.dcinside).
    ext_etlds = {_registered_domain(h) for h in ext_hosts if h}
    same_etld_only = bool(ext_etlds) and ext_etlds == {base_reg}
    return {
        "base_host": base_host,
        "base_registered_domain": base_reg,
        "total_count": total,
        "external_count": external,
        "external_ratio": ratio,
        "sample_external_urls": ext_samples,
        "unique_external_hosts": sorted(ext_hosts),
        "multi_host_hub": (len(ext_hosts) >= 3 and ratio >= 0.95 and not same_etld_only),
    }


_NAV_TAGS = frozenset(("nav", "aside", "header", "footer"))
_NAV_ROLES = frozenset(("navigation", "complementary", "banner", "contentinfo"))


@heuristic
def all_same_host_patterns_in_nav(
    html: str,
    html_candidates: list[dict],
    *,
    base_url: str,
) -> Optional[dict]:
    """모든 same-host repeating pattern 의 DOM ancestor 가 nav/aside/header/footer 안인가.
    True 면 single article 신호 — board 페이지의 main list 는 nav 밖에 있음 (main/article body 안).
    nav 안에만 같은-host 반복 링크가 있으면 = 사이드바/topic-nav/메뉴 = 폴링 의미 없음.

    트리거 조건: total_same_host ≥ 1 AND outside_nav == 0.

    출력:
      None — 같은-host 의미 있는 row 후보 0건 (판정 불가 — 외부도메인 검색결과 등).
      dict = {base_host, total_same_host, in_nav, outside_nav, nav_only_same_host, sample_nav_ancestors}
        sample_nav_ancestors: 어떤 nav-tag 안이었는지 샘플 (debug/case 작성용).

    `_single_article_nav_only_check` (scripts/register.py) 가 이 신호 보고 거부.
    """
    if not html or not html_candidates:
        return None
    from urllib.parse import urlsplit
    base_host = (urlsplit(base_url or "").netloc or "").lower()
    if not base_host:
        return None
    same_host = [c for c in html_candidates
                 if (urlsplit(c.get("sample_url") or "").netloc or "").lower() == base_host]
    if not same_host:
        return None
    soup = BeautifulSoup(html, "lxml")
    in_nav = 0
    outside_nav = 0
    sample_nav: list[str] = []
    for c in same_host:
        sel = c.get("selector") or ""
        if not sel:
            continue
        try:
            el = soup.select_one(sel)
        except Exception:  # noqa: BLE001  selector 문법 오류 시 skip
            continue
        if el is None:
            continue
        nav_anc = _find_nav_ancestor(el)
        if nav_anc:
            in_nav += 1
            if len(sample_nav) < 4:
                sample_nav.append(nav_anc)
        else:
            outside_nav += 1
    total = in_nav + outside_nav
    if total == 0:
        return None
    return {
        "base_host": base_host,
        "total_same_host": total,
        "in_nav": in_nav,
        "outside_nav": outside_nav,
        "nav_only_same_host": outside_nav == 0,
        "sample_nav_ancestors": sample_nav,
    }


_MARKETING_SELECTOR_KEYWORDS = (
    "nav", "footer", "header", "dropdown", "subnav", "menu",
    "carousel", "swiper", "tile", "promo", "hero", "banner",
)


_DISCOURSE_GENERATOR_RE = re.compile(
    r'<meta[^>]+name=["\']generator["\'][^>]*content=["\']\s*Discourse'
    r'(?:\s+(?P<ver>[\w.\-]+))?',
    re.I,
)

_WORDPRESS_GENERATOR_RE = re.compile(
    r'<meta[^>]+name=["\']generator["\'][^>]*content=["\']\s*WordPress\b',
    re.I,
)


def _origin_from_url(url: str) -> Optional[str]:
    try:
        parts = urlsplit(url)
        host = (parts.netloc or "").strip().lower()
        scheme = parts.scheme or "https"
    except (ValueError, AttributeError):
        return None
    if not host or "." not in host:
        return None
    return f"{scheme}://{host}"


def _normalize_wp_api_base(api_href: Optional[str], base_url: str) -> Optional[str]:
    origin = _origin_from_url(base_url)
    if not origin:
        return None
    href = (api_href or "").strip()
    if href:
        try:
            full = urljoin(base_url, href)
            parts = urlsplit(full)
            host = (parts.netloc or "").strip().lower()
            if host and "." in host:
                path = parts.path or ""
                marker = "/wp-json"
                idx = path.lower().find(marker)
                if idx >= 0:
                    return f"{parts.scheme or 'https'}://{host}{path[:idx + len(marker)].rstrip('/')}"
        except (ValueError, AttributeError):
            pass
    return f"{origin}/wp-json"


@heuristic
def detect_wordpress_platform(html: str, base_url: str) -> Optional[dict]:
    """HTML head/static markers 로 WordPress REST API 를 쓰는 사이트 판정.

    URL root 만으로 WordPress 판정은 오탐이 크다. probe 가 받은 HTML 안의 REST API discovery
    link, generator meta, wp-content/wp-json asset marker 를 보고 register.py 가 LLM 전
    httpx_json config 등록을 시도한다. 이 함수는 네트워크 fetch 를 하지 않는다.
    """
    if not html or not base_url:
        return None
    if _origin_from_url(base_url) is None:
        return None
    soup = BeautifulSoup(html, "lxml")
    api_href: Optional[str] = None
    rest_link = soup.find("link", rel=lambda v: bool(v) and "https://api.w.org/" in (v if isinstance(v, str) else " ".join(v)))
    if isinstance(rest_link, Tag):
        api_href = str(rest_link.get("href") or "").strip() or None
    generator = bool(_WORDPRESS_GENERATOR_RE.search(html))
    low = html.lower()
    marker_hits = sum(1 for marker in ("/wp-content/", "/wp-includes/", "/wp-json/") if marker in low)
    if not (api_href or generator or marker_hits >= 2):
        return None
    api_base = _normalize_wp_api_base(api_href, base_url)
    if not api_base:
        return None
    return {
        "is_wordpress": True,
        "api_base": api_base,
        "posts_endpoint": f"{api_base}/wp/v2/posts",
    }


@heuristic
def detect_discourse_platform(html: str, base_url: str) -> Optional[dict]:
    """정적 HTML 의 `<meta name="generator" content="Discourse ...">` 로 Discourse 포럼 판정.

    Discourse 는 모든 페이지(root `/`, `/latest`, `/c/<cat>`, `/t/<id>`)에 이 generator meta 를
    박는다 — Ember.js shell 이라 topic rows 는 정적에 없어 `posts_nonempty: 0건` 으로 LLM 이 실패하지만,
    이 meta 는 항상 정적에 있다. 신뢰도 매우 높음(false-positive ~0) — Discourse 외 사이트는 안 박음.

    `engine/recognizers/discourse.py` 의 recognizer 는 URL `/latest` 폼만 매칭 — root 도메인
    (`https://forum.openwrt.org/`)은 URL 만으로 Discourse 판정 불가(모든 root 가 매칭되면 false-positive
    폭발)라 못 잡았다. 이 휴리스틱이 probe *후* generator meta 로 root-form 까지 봉합.

    출력:
      None — Discourse meta 없음.
      dict = {is_discourse: True, base_url: "<scheme>://<host>", version: "<x|null>"}.

    register.py 가 이 신호 보면 LLM 호출 *전* DiscourseAdapter config 를 만들어 등록 시도 — fetch_list
    가 빈 목록이면 일반 파이프라인으로 폴백(안전망)."""
    from urllib.parse import urlsplit
    if not html or not base_url:
        return None
    m = _DISCOURSE_GENERATOR_RE.search(html)
    if m is None:
        return None
    try:
        parts = urlsplit(base_url)
        host = (parts.netloc or "").strip().lower()
        scheme = parts.scheme or "https"
    except (ValueError, AttributeError):
        return None
    if not host or "." not in host:
        return None
    return {
        "is_discourse": True,
        "base_url": f"{scheme}://{host}",
        "version": m.group("ver") or None,
    }


@heuristic
def detect_medium_custom_domain(html: str, base_url: str) -> Optional[dict]:
    """Medium custom domain 판정.

    URL 만으로는 임의 blog host 와 구분할 수 없으므로 Medium 앱 meta, Medium canonical
    link, RSS alternate shape 를 함께 본다. 출력 feed_url 은 query 를 제거한 custom-domain
    `/feed` 계열 URL 이며 register.py 가 Medium RSS XML config 등록을 시도한다.
    """
    if not html or not base_url:
        return None
    origin = _origin_from_url(base_url)
    if not origin:
        return None
    try:
        host = (urlsplit(origin).netloc or "").lower()
    except ValueError:
        return None
    if host == "medium.com" or host.endswith(".medium.com"):
        return None

    soup = BeautifulSoup(html, "lxml")
    low = html.lower()
    has_medium_app = (
        'content="com.medium.reader"' in low
        or "content='com.medium.reader'" in low
        or 'content="medium"' in low and "al:ios:app_name" in low
    )
    has_medium_post_link = bool(re.search(r"https?://medium\.com/p/[0-9a-f]{10,}", html, re.I))
    feed_url: Optional[str] = None
    for link in soup.select('link[rel="alternate"][href]'):
        href = str(link.get("href") or "").strip()
        typ = str(link.get("type") or "").lower()
        if not href:
            continue
        full = urljoin(base_url, href)
        parts = urlsplit(full)
        path = parts.path or ""
        if ("rss" in typ or "xml" in typ or "atom" in typ) and (
            path.rstrip("/").endswith("/feed") or "source=rss-" in (parts.query or "")
        ):
            feed_url = urlunsplit((parts.scheme, parts.netloc, path.rstrip("/") or "/feed", "", ""))
            break
    if not (has_medium_app or has_medium_post_link):
        return None
    if not feed_url:
        feed_url = f"{origin}/feed"
    return {"is_medium_custom": True, "base_url": origin, "feed_url": feed_url}


@heuristic
def detect_common_platform(html: str, base_url: str) -> Optional[dict]:
    """Common/Commonwealth SPA shell marker 로 governance forum 판정.

    Common pages often return only an app shell (`<title>Common</title>`,
    `/assets/index-*`, `/brand_assets/common*`) while discussion rows come from
    `/api/internal/trpc/thread.getThreads`.  URL-only matching is intentionally
    limited to `common.xyz`/`commonwealth.im`; custom domains are routed through
    this probe signal and later verified by the adapter baseline.
    """
    from urllib.parse import urlsplit
    if not html or not base_url:
        return None
    try:
        parts = urlsplit(base_url)
        host = (parts.netloc or "").strip().lower()
        scheme = parts.scheme or "https"
    except (ValueError, AttributeError):
        return None
    if not host or "." not in host:
        return None

    low = html.lower()
    soup = BeautifulSoup(html, "lxml")
    title_common = bool(soup.find("title", string=lambda s: bool(s) and s.strip().lower() == "common"))
    og_common = bool(soup.find(
        "meta",
        attrs={"property": re.compile(r"^og:site_name$", re.I), "content": re.compile(r"^common$", re.I)},
    ))
    marker_hits = sum(1 for hit in (
        title_common,
        "/assets/index-" in low,
        "/brand_assets/common" in low,
        "/api/internal/trpc" in low,
        og_common,
    ) if hit)
    if marker_hits < 2:
        return None

    community_id: Optional[str] = None
    first_segment = (parts.path or "").strip("/").split("/", 1)[0].strip()
    if first_segment and first_segment.lower() not in {"discussions", "discussion"}:
        community_id = first_segment
    return {
        "is_common": True,
        "base_url": f"{scheme}://{host}",
        "community_id_hint": community_id,
    }


# XenForo: 모든 public 페이지가 `<html id="XF" ... data-app="public">` + `XF.config` JS 를 박는다.
# generator meta 는 없지만 이 두 마커는 false-positive ~0 (XenForo 외 사이트 안 씀). Discourse 와 같은 이유로
# root URL 만으론 URL-recognizer 가 못 잡아 → probe 후 이 휴리스틱이 봉합.
_XENFORO_MARKER_RE = re.compile(r'<html[^>]+\bid=["\']XF["\']|XF\.config\s*=', re.I)


def detect_xenforo_platform(html: str, base_url: str) -> Optional[dict]:
    """렌더된 HTML 의 `<html id="XF">` / `XF.config` 마커로 XenForo 포럼 판정.

    XenForo 는 `<base>/forums/-/index.rss` 전역 RSS(최근 thread 50건; guid=thread id, title,
    link, pubDate, content:encoded 본문)를 제공 — Cloudflare 가 root 는 막아도 RSS 는 허용하는
    경우가 많아(wordreference·hardforum 확인) httpx 로 안정 수집된다. register.py 가 이 신호 보면
    LLM 전 `engine/recognizers/xenforo.build_config` 로 RSS config 등록 시도 → fetch_list 빈
    목록(RSS 404/빈/차단)이면 일반 파이프라인 폴백(안전망).

    출력: None | {is_xenforo: True, base_url: "<scheme>://<host>[/<install>]"}.
    base_url 의 path 에서 install path 보존 (서브폴더 설치 — xenforo.com/community).
    """
    from urllib.parse import urlsplit
    from engine.recognizers.xenforo import _install_path
    if not html or not base_url:
        return None
    if _XENFORO_MARKER_RE.search(html) is None:
        return None
    try:
        parts = urlsplit(base_url)
        host = (parts.netloc or "").strip().lower()
        scheme = parts.scheme or "https"
    except (ValueError, AttributeError):
        return None
    if not host or "." not in host:
        return None
    install = _install_path(parts.path or "")
    return {"is_xenforo": True, "base_url": f"{scheme}://{host}{install}"}


_LEMMY_MARKERS = (
    "window.isoData",
    '"site_res"',
    '"local_site"',
    '"default_post_listing_type"',
    "join-lemmy.org",
    "/api/v3/",
)


@heuristic
def detect_lemmy_platform(html: str, base_url: str) -> Optional[dict]:
    """Lemmy SSR/app-shell marker 로 Lemmy instance 판정.

    Root URL 은 URL 만으론 판정할 수 없어 recognizer 가 직접 잡지 않는다. probe 후
    `window.isoData` + `site_res.local_site`, join-lemmy 링크, `/api/v3` 같은 Lemmy 고유
    마커를 확인해 LemmyAdapter 등록으로 넘긴다.
    """
    from urllib.parse import urlsplit
    if not html or not base_url:
        return None
    try:
        parts = urlsplit(base_url)
        host = (parts.netloc or "").strip().lower()
        scheme = parts.scheme or "https"
    except (ValueError, AttributeError):
        return None
    if not host or "." not in host:
        return None

    low = html.lower()
    strong = "window.isodata" in low and '"site_res"' in low and '"local_site"' in low
    weak_hits = sum(1 for marker in _LEMMY_MARKERS if marker.lower() in low)
    og_lemmy = bool(re.search(
        r'<meta[^>]+(?:property|name)=["\'](?:og:title|description)["\'][^>]+content=["\']lemmy\s+-\s+a community\b',
        html,
        re.I,
    ))
    if not (strong or weak_hits >= 3 or og_lemmy):
        return None
    out = {"is_lemmy": True, "base_url": f"{scheme}://{host}"}
    m = re.match(r"^/c/([^/?#]+)/*$", parts.path or "", re.I)
    if m is not None:
        out["community_name"] = m.group(1)
    return out


@heuristic
def detect_mastodon_platform(html: str, base_url: str) -> Optional[dict]:
    """Mastodon app-shell marker 로 social instance 판정.

    Mastodon root/about 는 firehose 성격의 social client shell 이지 notice board 가 아니다.
    register.py 가 이 신호를 보면 LLM 호출 전 REJECTED 로 종료한다.
    """
    from urllib.parse import urlsplit
    if not html or not base_url:
        return None
    try:
        parts = urlsplit(base_url)
        host = (parts.netloc or "").strip().lower()
        scheme = parts.scheme or "https"
    except (ValueError, AttributeError):
        return None
    if not host or "." not in host:
        return None

    marker_hit = any((
        re.search(r'<div[^>]+\bid=["\']mastodon["\']', html, re.I) is not None,
        re.search(r'"meta"\s*:\s*\{[^{}]*"streaming_api"', html, re.I | re.S) is not None,
        re.search(r'<link[^>]+href=["\'][^"\']*/api/v1/streaming\b', html, re.I) is not None,
        re.search(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\'][^"\']*mastodon', html, re.I) is not None,
    ))
    if not marker_hit:
        return None
    return {"is_mastodon": True, "base_url": f"{scheme}://{host}"}


@heuristic
def detect_misskey_platform(html: str, base_url: str) -> Optional[dict]:
    """Misskey app-shell marker 로 social instance 판정."""
    from urllib.parse import urlsplit
    if not html or not base_url:
        return None
    try:
        parts = urlsplit(base_url)
        host = (parts.netloc or "").strip().lower()
        scheme = parts.scheme or "https"
    except (ValueError, AttributeError):
        return None
    if not host or "." not in host:
        return None

    marker_hit = any((
        re.search(r'<meta[^>]+property=["\']og:[^"\']*["\'][^>]+content=["\'][^"\']*misskey', html, re.I) is not None,
        "_misskey_" in html.lower(),
        "window.__misskey" in html,
        re.search(r"<title[^>]*>[^<]*misskey[^<]*</title>", html, re.I) is not None,
    ))
    if not marker_hit:
        return None
    return {"is_misskey": True, "base_url": f"{scheme}://{host}"}


@heuristic
def detect_pixelfed_platform(html: str, base_url: str) -> Optional[dict]:
    """Pixelfed app-shell marker 로 social instance 판정."""
    from urllib.parse import urlsplit
    if not html or not base_url:
        return None
    try:
        parts = urlsplit(base_url)
        host = (parts.netloc or "").strip().lower()
        scheme = parts.scheme or "https"
    except (ValueError, AttributeError):
        return None
    if not host or "." not in host:
        return None

    low = html.lower()
    marker_hit = any((
        re.search(r'<meta[^>]+(?:name|property)=["\'][^"\']*["\'][^>]+content=["\'][^"\']*pixelfed', html, re.I) is not None,
        "<noscript" in low and "pixelfed" in low,
        "window.app.config" in low and "pixelfed" in low,
        re.search(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\'][^"\']*pixelfed', html, re.I) is not None,
    ))
    if not marker_hit:
        return None
    return {"is_pixelfed": True, "base_url": f"{scheme}://{host}"}


_PEERTUBE_MARKERS = (
    'property="og:platform" content="PeerTube"',
    "window.PeerTubeServerConfig",
    "/api/v1/config",
    "joinpeertube",
)


@heuristic
def detect_peertube_platform(html: str, base_url: str) -> Optional[dict]:
    """PeerTube app-shell marker 로 PeerTube instance 판정."""
    from urllib.parse import urlsplit
    if not html or not base_url:
        return None
    try:
        parts = urlsplit(base_url)
        host = (parts.netloc or "").strip().lower()
        scheme = parts.scheme or "https"
    except (ValueError, AttributeError):
        return None
    if not host or "." not in host:
        return None
    low = html.lower()
    strong = (
        re.search(r'<meta[^>]+property=["\']og:platform["\'][^>]+content=["\']peertube["\']', html, re.I)
        is not None
    )
    weak_hits = sum(1 for marker in _PEERTUBE_MARKERS if marker.lower() in low)
    title_hit = bool(re.search(r"<title[^>]*>[^<]*peertube[^<]*</title>", html, re.I))
    if not (strong or weak_hits >= 2 or title_hit):
        return None
    return {"is_peertube": True, "base_url": f"{scheme}://{host}"}


@heuristic
def detect_mbin_platform(html: str, base_url: str) -> Optional[dict]:
    """Mbin/kbin marker 로 threadiverse aggregator instance 판정."""
    from urllib.parse import urlsplit
    if not html or not base_url:
        return None
    try:
        parts = urlsplit(base_url)
        host = (parts.netloc or "").strip().lower()
        scheme = parts.scheme or "https"
    except (ValueError, AttributeError):
        return None
    if not host or "." not in host:
        return None
    low = html.lower()
    data_controller = bool(re.search(r'\bdata-controller=["\'][^"\']*\b(?:mbin|kbin)\b', html, re.I))
    meta_hit = ("mbin" in low or "kbin" in low) and ("fediverse" in low or "content aggregator" in low)
    route_hit = all(token in low for token in ("/threads", "/microblog", "/magazines"))
    if not (data_controller or (meta_hit and route_hit)):
        return None
    out = {"is_mbin": True, "base_url": f"{scheme}://{host}"}
    m = re.match(r"^/m/([^/?#]+)", parts.path or "", re.I)
    if m is not None:
        out["magazine_name"] = m.group(1)
    return out


@heuristic
def root_marketing_homepage(
    *,
    base_url: str,
    html_candidates: list[dict],
    nav_only_same_host: Optional[dict],
    body_empty_likely: bool,
) -> Optional[dict]:
    """root 도메인 URL 의 마케팅 랜딩/허브 페이지 검출 — board 정의 자체 X.

    트리거 조건 (AND):
      1. URL path == '/' (또는 빈 path) — root 도메인
      2. html_repeating_patterns top 7 중 selector 에 nav/footer/header/dropdown/subnav/menu/
         carousel/swiper/tile/promo/hero/banner 키워드 ≥ 2 (마케팅 구조 우세)
      3. nav_only_same_host.total_same_host ≤ 15 (또는 None) — 진짜 article-grid root
         (예: HackerNews) false-positive 차단. 진짜 board root 면 same-host article rows
         가 보통 ≥ 30.

    출력:
      None — 조건 미충족 (정상 board 가능성).
      dict = {is_root_marketing_homepage, marketing_hits, marketing_selectors, total_same_host,
              body_empty_likely}.

    register.py `_root_marketing_homepage_check` 가 이 신호 보고 LLM 호출 *전* REJECTED
    마커 박음 + 사용자에 카테고리/섹션 URL 권장. learn=False — root 만 차단, 카테고리 path
    는 진짜 board 가능성 있어 path_prefix 차단 안 함.
    """
    from urllib.parse import urlsplit
    if not base_url:
        return None
    try:
        parts = urlsplit(base_url)
        path = (parts.path or "").strip()
        host = (parts.netloc or "").strip()
    except (ValueError, AttributeError):
        return None
    if not host:
        return None
    if path and path != "/":
        return None
    if not html_candidates:
        return None
    top = html_candidates[:7]
    matched: list[str] = []
    for c in top:
        sel = (c.get("selector") or "").lower()
        if not sel:
            continue
        if any(kw in sel for kw in _MARKETING_SELECTOR_KEYWORDS):
            matched.append((c.get("selector") or "")[:120])
    if len(matched) < 2:
        return None
    nav = nav_only_same_host if isinstance(nav_only_same_host, dict) else {}
    total_same = int(nav.get("total_same_host") or 0)
    if total_same > 15:
        return None
    return {
        "is_root_marketing_homepage": True,
        "marketing_hits": len(matched),
        "marketing_selectors": matched[:5],
        "total_same_host": total_same,
        "body_empty_likely": bool(body_empty_likely),
    }


def _find_nav_ancestor(el: Tag) -> Optional[str]:
    p = el.parent
    while p is not None and getattr(p, "name", None):
        name = p.name
        if name in _NAV_TAGS:
            ide = "#" + p.get("id") if hasattr(p, "get") and p.get("id") else ""
            return f"{name}{ide}"
        role = p.get("role") if hasattr(p, "get") else None
        if role in _NAV_ROLES:
            return f"[role={role}]"
        p = p.parent
    return None


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


# schema.org 의 single-article 타입들 — JSON-LD `@type` 또는 microdata `itemtype` 의 끝부분 매칭.
# https://schema.org/CreativeWork 의 article-shaped 하위 타입. board/list 형식은 제외 (ItemList, Collection 등).
_SCHEMA_ARTICLE_TYPES = frozenset((
    "article", "newsarticle", "blogposting", "scholarlyarticle",
    "techarticle", "report", "socialmediaposting", "discussionforumposting",
    "review", "medicalscholarlyarticle", "analysisnewsarticle", "opinionnewsarticle",
    "reportagenewsarticle", "backgroundnewsarticle", "satiricalarticle",
))


@heuristic
def article_meta_signals(html: str) -> Optional[dict]:
    """페이지가 *단일 article* 임을 선언하는 명시적 meta 신호 추출.
    schema.org JSON-LD `@type` (NewsArticle/Article/BlogPosting/...) + og:type=article + microdata itemtype.

    출력:
      None — 신호 0건 (페이지가 article 페이지인지 알 수 없음 — 보드/landing/검색결과 모두 가능).
      dict = {has_og_article: bool, schema_article_types: [str], has_microdata_article: bool,
              is_article_page: bool, signals: [str]}
        is_article_page=True 면 위 3 신호 중 *하나라도* 매칭됨. 보드 페이지가 NewsArticle 마크업
        쓰는 일은 드물어 (보통 ItemList/Collection) — false-positive 위험 낮음.

    register.py 의 `_meta_article_diverging_check` 가 이 신호 + first_article_url path 발산 검사 결합하여
    `recognize_reject` 미커버 호스트의 단일 article 페이지를 잡음. board 페이지가 *우연히* og:type=article
    을 박은 경우(omate 등) 는 first_article_url 이 input 과 같은 path-prefix → 통과.
    """
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    signals: list[str] = []

    has_og_article = False
    og = soup.find("meta", attrs={"property": re.compile(r"^og:type$", re.I)})
    if og and (og.get("content") or "").strip().lower() == "article":
        has_og_article = True
        signals.append("og:type=article")

    schema_types: list[str] = []
    for sc in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        raw = sc.string or sc.get_text() or ""
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        for node in _walk_schema_types(data):
            t = (node or "").strip().lower()
            if t and t in _SCHEMA_ARTICLE_TYPES:
                schema_types.append(node.strip() if isinstance(node, str) else str(node))
    if schema_types:
        signals.append(f"schema.org/{schema_types[0]}")

    has_microdata = False
    for el in soup.find_all(attrs={"itemtype": True}):
        it = (el.get("itemtype") or "").strip().lower().rstrip("/")
        # itemtype 는 보통 https://schema.org/NewsArticle 같은 풀 URL — 끝 segment 만 비교.
        tail = it.rsplit("/", 1)[-1]
        if tail in _SCHEMA_ARTICLE_TYPES:
            has_microdata = True
            signals.append(f"microdata/{tail}")
            break

    if not signals:
        return None
    return {
        "has_og_article": has_og_article,
        "schema_article_types": schema_types[:5],
        "has_microdata_article": has_microdata,
        "is_article_page": True,
        "signals": signals[:5],
    }


def _walk_schema_types(node, _depth: int = 0):
    """JSON-LD blob 안의 모든 `@type` scalar 를 yield. dict/list 양쪽 재귀. 최대 depth 8.
    `@type` 가 list 일 수도 있음 (`["NewsArticle","Article"]`) — 그 안 각 entry yield."""
    if _depth > 8:
        return
    if isinstance(node, dict):
        t = node.get("@type")
        if isinstance(t, str):
            yield t
        elif isinstance(t, list):
            for x in t:
                if isinstance(x, str):
                    yield x
        for v in node.values():
            if isinstance(v, (dict, list)):
                yield from _walk_schema_types(v, _depth + 1)
    elif isinstance(node, list):
        for v in node:
            if isinstance(v, (dict, list)):
                yield from _walk_schema_types(v, _depth + 1)


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


_RSS_LINK_TYPE_RE = re.compile(r"(rss|atom)\+xml", re.IGNORECASE)
_RSS_BODY_HREF_RE = re.compile(r"(?:^|[/_.-])(rss|feed|atom)(?:[/_.-]|$)", re.IGNORECASE)
_RSS_CONTENT_TYPE_RE = re.compile(r"(application/(?:rss|atom)\+xml|text/xml|application/xml)", re.IGNORECASE)
_RSS_XML_ROOT_RE = re.compile(r"^\s*(?:<\?xml[^>]*>\s*)?(?:<rss\b|<feed\b|<rdf:RDF\b)", re.IGNORECASE)


@heuristic
def rss_feed_urls(*, html: str, base_url: str, har_path: Optional[Path] = None) -> list[dict]:
    """RSS/Atom feed URL 후보를 LLM digest 에 직접 노출한다.

    discover_feeds 의 검증 후보와 별개로, config writer 가 `list.url_template` 을 추측하지 않도록
    페이지 HTML 과 HAR 에서 실제 feed URL 을 보존한다.
    """
    out: list[dict] = []
    seen: set[str] = set()

    def add(url: str, *, source: str, typ: Optional[str] = None) -> None:
        if not url:
            return
        abs_url = urljoin(base_url, url)
        if abs_url in seen:
            return
        seen.add(abs_url)
        item = {"url": abs_url, "source": source}
        if typ:
            item["type"] = typ
        out.append(item)

    if html:
        soup = BeautifulSoup(html, "lxml")
        for link in soup.find_all("link"):
            if not isinstance(link, Tag):
                continue
            rel = " ".join(str(x).lower() for x in (link.get("rel") or []))
            typ = str(link.get("type") or "")
            href = str(link.get("href") or "")
            if "alternate" in rel and _RSS_LINK_TYPE_RE.search(typ):
                add(href, source="link_rel", typ=typ)
        for a in soup.find_all("a", href=True):
            if not isinstance(a, Tag):
                continue
            href = str(a.get("href") or "")
            if _RSS_BODY_HREF_RE.search(urlsplit(href).path or href):
                add(href, source="html_body")

    if har_path and har_path.exists():
        try:
            har = json.loads(har_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            har = {}
        for entry in ((har.get("log") or {}).get("entries") or []):
            req = entry.get("request") or {}
            resp = entry.get("response") or {}
            url = req.get("url") or ""
            ct = ""
            for h in resp.get("headers") or []:
                if str(h.get("name") or "").lower() == "content-type":
                    ct = str(h.get("value") or "")
                    break
            if not url or not _RSS_CONTENT_TYPE_RE.search(ct):
                continue
            text = _har_entry_response_text(entry, har_path)
            if _RSS_XML_ROOT_RE.search(text or ""):
                add(url, source="har_resp_xml", typ=ct)

    return out


_AUDIO_SHARE_KNOWN_HOST_SUFFIXES = (
    "transistor.fm",
    "libsyn.com",
    "simplecast.com",
    "art19.com",
    "megaphone.fm",
)
_AUDIO_SHARE_PATH_RE = re.compile(
    r"(?:\.(?:mp3|m4a|ogg|oga|wav)(?:$|[?#])|/(?:episodes?|s|e)/[^/?#]+)",
    re.IGNORECASE,
)
_AUDIO_SHARE_AUDIO_CT_RE = re.compile(r"^(?:audio/|video/)|^application/ogg(?:\b|;)", re.IGNORECASE)
_AUDIO_SHARE_HTML_CT_RE = re.compile(r"^text/html(?:\b|;)", re.IGNORECASE)


def _is_audio_share_host(host: str) -> bool:
    h = (host or "").lower().split(":", 1)[0]
    return any(h == suffix or h.endswith("." + suffix) for suffix in _AUDIO_SHARE_KNOWN_HOST_SUFFIXES)


def _har_content_type(entry: dict) -> str:
    resp = entry.get("response") or {}
    for h in resp.get("headers") or []:
        if str(h.get("name") or "").lower() == "content-type":
            return str(h.get("value") or "")
    return str(((resp.get("content") or {}).get("mimeType") or ""))


def _matching_har_entry(har_entries: list[dict], url: str) -> Optional[dict]:
    target = (url or "").split("#", 1)[0]
    if not target:
        return None
    for entry in har_entries:
        req = entry.get("request") or {}
        got = str(req.get("url") or "").split("#", 1)[0]
        if got == target:
            return entry
    return None


def _audio_share_structural_evidence(url: str, har_entry: Optional[dict], har_path: Optional[Path]) -> Optional[str]:
    if har_entry:
        ct = _har_content_type(har_entry)
        if _AUDIO_SHARE_AUDIO_CT_RE.search(ct):
            return "har_content_type_audio"
        if _AUDIO_SHARE_HTML_CT_RE.search(ct):
            body = _har_entry_response_text(har_entry, har_path) if har_path else ""
            size = len(body.encode("utf-8"))
            content = (har_entry.get("response") or {}).get("content") or {}
            if not body and isinstance(content.get("size"), int):
                size = int(content.get("size") or 0)
            if size < 1024:
                return "har_tiny_html_player"
    if _AUDIO_SHARE_PATH_RE.search(urlsplit(url).path or ""):
        return "url_path_audio_player"
    return None


@heuristic
def audio_share_host_detected(
    *,
    base_url: str,
    first_article_url: Optional[str],
    html_candidates: list[dict],
    har_path: Optional[Path] = None,
) -> Optional[dict]:
    """Podcast RSS item link 가 외부 audio share/player host 를 가리키는지 감지한다."""
    base_host = urlsplit(base_url or "").netloc.lower().split(":", 1)[0]
    urls: list[str] = []
    if first_article_url:
        urls.append(first_article_url)
    for cand in html_candidates or []:
        sample = cand.get("sample_url")
        if isinstance(sample, str):
            urls.append(sample)

    har_entries: list[dict] = []
    if har_path and har_path.exists():
        try:
            har = json.loads(har_path.read_text(encoding="utf-8", errors="replace"))
            har_entries = ((har.get("log") or {}).get("entries") or [])
        except Exception:
            har_entries = []

    for url in urls[:10]:
        abs_url = urljoin(base_url, url)
        host = urlsplit(abs_url).netloc.lower().split(":", 1)[0]
        if not host or host == base_host:
            continue
        evidence = _audio_share_structural_evidence(
            abs_url,
            _matching_har_entry(har_entries, abs_url),
            har_path,
        )
        if evidence:
            return {
                "audio_share_host_detected": True,
                "host": host,
                "base_host": base_host,
                "sample_url": abs_url,
                "confidence": "structural",
                "evidence": evidence,
            }
        if _is_audio_share_host(host):
            return {
                "audio_share_host_detected": True,
                "host": host,
                "base_host": base_host,
                "sample_url": abs_url,
                "confidence": "host_known",
                "evidence": "known_host_suffix",
            }
    return None


def _audio_share_from_feed_urls(*, base_url: str, feeds: list[dict]) -> Optional[dict]:
    base_host = urlsplit(base_url or "").netloc.lower().split(":", 1)[0]
    for feed in feeds or []:
        url = feed.get("url") if isinstance(feed, dict) else None
        if not isinstance(url, str):
            continue
        host = urlsplit(url).netloc.lower().split(":", 1)[0]
        if host and host != base_host and _is_audio_share_host(host):
            return {
                "audio_share_host_detected": True,
                "host": host,
                "base_host": base_host,
                "sample_url": url,
                "source": "rss_feed_urls",
                "confidence": "host_known",
                "evidence": "known_host_suffix",
            }
    return None


def audio_share_signal(
    *,
    base_url: str,
    first_article_url: Optional[str],
    html_candidates: list[dict],
    feeds: list[dict],
    har_path: Optional[Path] = None,
) -> Optional[dict]:
    return (
        audio_share_host_detected(
            base_url=base_url,
            first_article_url=first_article_url,
            html_candidates=html_candidates,
            har_path=har_path,
        )
        or _audio_share_from_feed_urls(base_url=base_url, feeds=feeds)
    )


# URL pagination heuristic — 사이트의 페이지네이션 query param 자동 감지.
# Radiolab 류 SPA 가 `?page={page}` query 없으면 cards 안 그리는 케이스 봉합용. probe 두 신호:
#   1. 정적 HTML anchor — `<a href="...?page=N">` 류 직접 박힌 pagination 링크
#   2. HAR XHR fetch URL — SPA 의 클라이언트 fetch URL 에 `page=N` 또는 path `/N` 박힌 것
# config writer 가 list.url_template + list.pagination 박을 때 hint 로 사용.

_PAGE_PARAM_NAMES = ("page", "p", "pg", "offset", "start", "skip", "cursor", "_page", "page_num")
_PAGE_PARAM_RE = re.compile(
    r"[?&](" + "|".join(re.escape(n) for n in _PAGE_PARAM_NAMES) + r")=(\d+)",
    re.IGNORECASE,
)
# path-segment pagination — `/page/N` at path end (atlus/fate-go/WordPress archives 류).
# `/p/N` 은 ambiguous (`/p/posts/` 등) 라 채택 X — `/page/N` 만.
_PATH_PAGE_RE = re.compile(r"/page/(\d+)/?$", re.IGNORECASE)


def _pagination_path_template(url: str) -> Optional[str]:
    """url 의 `/page/N` 자리에 `{page}` 박은 url_template 반환. 실패 시 None.

    예: `https://www.atlus.co.jp/news/page/2` → `https://www.atlus.co.jp/news/page/{page}`.
    """
    try:
        sp = urlsplit(url)
    except ValueError:
        return None
    m = _PATH_PAGE_RE.search(sp.path)
    if not m:
        return None
    trailing_slash = sp.path.endswith("/")
    new_path = sp.path[:m.start()] + "/page/{page}"
    if trailing_slash:
        new_path += "/"
    return urlunsplit((sp.scheme, sp.netloc, new_path, sp.query, ""))


def _pagination_url_template(url: str, param: str) -> Optional[str]:
    """url 의 `?{param}=N` 자리에 `{page}` 박은 url_template 반환. 실패 시 None."""
    try:
        sp = urlsplit(url)
    except ValueError:
        return None
    if not sp.query:
        return None
    pairs = parse_qsl(sp.query, keep_blank_values=True)
    out_pairs = []
    found = False
    for k, v in pairs:
        if k.lower() == param.lower():
            out_pairs.append((k, "{page}"))
            found = True
        else:
            out_pairs.append((k, v))
    if not found:
        return None
    new_q = "&".join(f"{k}={v}" for k, v in out_pairs)
    return urlunsplit((sp.scheme, sp.netloc, sp.path, new_q, ""))


@heuristic
def pagination_hints(html: str, *, base_url: str, har_path: Optional[Path] = None) -> list[dict]:
    """페이지네이션 후보 추출 — 두 source 종합 (html anchor + HAR XHR).

    출력: [{kind, param, url_template, source, evidence_url}, ...] — confidence 순.
      - kind: "query_param" (`?page=N` 형식) | "path_segment" (`/page/N` 형식).
      - param: 검출된 param 이름 (query_param) 또는 "page" (path_segment 고정).
      - url_template: base_url 기반 `?{param}={{page}}` 박은 URL. *page_url 의 path* 에 박음
        (XHR 의 API host 가 다른 경우 — 예: Radiolab radiolab.org 인데 XHR api.wnyc.org —
        config 의 list.url_template 은 page URL 의 path 에 query 박은 게 맞음).
      - source: "html_anchor" | "har_xhr" — 진단/디버그용.
      - evidence_url: 검출 원본 URL (LLM 한테 신뢰도 가늠 시 참고).

    fail-safe: html/har 둘 다 신호 없으면 빈 list. base_url 의 page 자리 박을 query 가 없는
    `/podcast` 같은 path 도 `?{param}={page}` 추가해서 후보 박음 (Radiolab 케이스).
    """
    hints: list[dict] = []
    seen: set[tuple[str, str]] = set()  # (param, url_template) 중복 제거

    # (1) HTML anchor pagination — query_param + path_segment 동시 스캔
    if html:
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = None
        if soup:
            base_host = (urlsplit(base_url).netloc or "").lower() if base_url else ""
            # path_segment 누적: stem(`/news/page/`) → {page_numbers}, evidence_url first.
            # in_pager_class: 같은 stem 이 `class~="pager|pagination|paging"` 안에 박혀있나 — fate-go
            # 류 "Next → /page/2/" 단일 링크라도 pager wrapper 안이면 board pagination 신호.
            path_stem_pages: dict[str, set[str]] = {}
            path_stem_evidence: dict[str, str] = {}
            path_stem_in_pager: dict[str, bool] = {}
            pager_class_re = re.compile(r"\b(pager|pagination|paging|page-nav)\b", re.IGNORECASE)
            for a in soup.find_all("a", href=True)[:500]:  # 첫 500 만 검사
                href = a.get("href") or ""
                if not isinstance(href, str):
                    continue
                abs_url = urljoin(base_url, href)
                # 1a. query_param 스타일
                m_q = _PAGE_PARAM_RE.search(href)
                if m_q:
                    param = m_q.group(1).lower()
                    tmpl_q = _pagination_url_template(abs_url, param)
                    if tmpl_q:
                        key_q = (param, tmpl_q)
                        if key_q not in seen:
                            seen.add(key_q)
                            hints.append({
                                "kind": "query_param",
                                "param": param,
                                "url_template": tmpl_q,
                                "source": "html_anchor",
                                "evidence_url": abs_url,
                            })
                # 1b. path_segment 스타일 (`/page/N`) — same-host 만 누적
                sp_abs = urlsplit(abs_url)
                if base_host and (sp_abs.netloc or "").lower() != base_host:
                    continue
                m_p = _PATH_PAGE_RE.search(sp_abs.path)
                if not m_p:
                    continue
                page_num = m_p.group(1)
                stem = sp_abs.path[:m_p.start()] + "/page/"
                path_stem_pages.setdefault(stem, set()).add(page_num)
                path_stem_evidence.setdefault(stem, abs_url)
                # ancestor class 검사 — `<div class="pager">` ... `<a href="/page/2/">`
                in_pager = False
                for anc in a.parents:
                    if getattr(anc, "name", None) is None:
                        continue
                    cls = anc.get("class") if hasattr(anc, "get") else None
                    if cls and pager_class_re.search(" ".join(cls)):
                        in_pager = True
                        break
                if in_pager:
                    path_stem_in_pager[stem] = True
            # emit 조건: ≥2 distinct page numbers OR pager-class wrapper.
            # 단일 `/page/N` 만 있어도 pager-class 안이면 board pagination 강신호 (fate-go 류 Next→ only).
            for stem, pages in path_stem_pages.items():
                if len(pages) < 2 and not path_stem_in_pager.get(stem):
                    continue
                ev = path_stem_evidence[stem]
                tmpl_p = _pagination_path_template(ev)
                if not tmpl_p:
                    continue
                key_p = ("page", tmpl_p)
                if key_p in seen:
                    continue
                seen.add(key_p)
                hints.append({
                    "kind": "path_segment",
                    "param": "page",
                    "url_template": tmpl_p,
                    "source": "html_anchor",
                    "evidence_url": ev,
                })

    # (2) HAR XHR pagination — SPA 의 fetch URL 에 page param 박힌 것
    if har_path and Path(har_path).exists():
        try:
            har = json.loads(Path(har_path).read_text(encoding="utf-8", errors="replace"))
        except Exception:
            har = None
        if har and isinstance(har, dict):
            base_host = urlsplit(base_url).netloc if base_url else ""
            xhr_params_found: dict[str, str] = {}  # param → first evidence URL
            for entry in (har.get("log", {}).get("entries", []) or [])[:200]:
                req = entry.get("request", {}) or {}
                xhr_url = req.get("url") or ""
                if not xhr_url:
                    continue
                # ad/tracker skip
                if _AD_TRACKER_RE.search(xhr_url):
                    continue
                # resourceType 으로 xhr/fetch 만 잡되, HAR 에 _resourceType 안 박힌 경우(일부
                # playwright HAR config)는 fallback — 정적 asset 확장자 명확히 제외 후
                # content-type=json 또는 URL 패턴(/api/, /graphql)으로 데이터 호출 추정.
                rtype = _entry_resource_type(entry)
                if rtype and rtype not in ("xhr", "fetch"):
                    continue
                if not rtype:
                    path_lower = urlsplit(xhr_url).path.lower()
                    if any(path_lower.endswith(ext) for ext in (
                        ".js", ".css", ".html", ".htm", ".png", ".jpg", ".jpeg",
                        ".gif", ".svg", ".webp", ".ico", ".woff", ".woff2", ".ttf",
                        ".mp4", ".webm", ".mp3", ".wav", ".pdf",
                    )):
                        continue
                    resp = entry.get("response", {}) or {}
                    content = resp.get("content", {}) or {}
                    ct = ""
                    for h in resp.get("headers", []) or []:
                        if str(h.get("name", "")).lower() == "content-type":
                            ct = h.get("value", "") or ""
                            break
                    looks_data = (
                        "json" in (ct.lower() + " " + str(content.get("mimeType", "")).lower())
                        or "/api/" in path_lower
                        or "/graphql" in path_lower
                    )
                    if not looks_data:
                        continue
                m = _PAGE_PARAM_RE.search(xhr_url)
                if not m:
                    continue
                param = m.group(1).lower()
                if param not in xhr_params_found:
                    xhr_params_found[param] = xhr_url

            # XHR 에 검출된 param 을 base_url 의 path 에 `?{param}={page}` 박아 후보 생성
            # (Radiolab: XHR=api.wnyc.org, page URL=radiolab.org/podcast → config url_template
            #  = `radiolab.org/podcast?{param}={page}`).
            for param, ev_url in xhr_params_found.items():
                try:
                    sp = urlsplit(base_url)
                    new_q_pairs = list(parse_qsl(sp.query, keep_blank_values=True))
                    # base_url 에 이미 같은 param 있으면 그 자리에 박음, 없으면 추가
                    found_in_base = False
                    for i, (k, v) in enumerate(new_q_pairs):
                        if k.lower() == param:
                            new_q_pairs[i] = (k, "{page}")
                            found_in_base = True
                            break
                    if not found_in_base:
                        new_q_pairs.append((param, "{page}"))
                    new_q = "&".join(f"{k}={v}" for k, v in new_q_pairs)
                    tmpl = urlunsplit((sp.scheme, sp.netloc, sp.path, new_q, ""))
                except Exception:
                    continue
                key = (param, tmpl)
                if key in seen:
                    continue
                seen.add(key)
                hints.append({
                    "kind": "query_param",
                    "param": param,
                    "url_template": tmpl,
                    "source": "har_xhr",
                    "evidence_url": ev_url,
                })

    return hints[:8]  # top 8 cap (token cost)


def write_list_candidates(
    out_dir: Path,
    *,
    base_url: str,
    page_html: str = "",
    har_path: Optional[Path] = None,
    html_candidates: list[dict],
    json_api_candidates: list[dict],
    hydration_candidates: list[dict],
    first_article_url: Optional[str],
    inline_js_candidates: Optional[list[dict]] = None,
    runtime_ids: Optional[list[dict]] = None,
    row_external_host: Optional[dict] = None,
    row_interactive_action: Optional[dict] = None,
    nav_only_same_host: Optional[dict] = None,
    article_meta_signals: Optional[dict] = None,
    wordpress_platform: Optional[dict] = None,
    discourse_platform: Optional[dict] = None,
    common_platform: Optional[dict] = None,
    xenforo_platform: Optional[dict] = None,
    medium_custom_domain: Optional[dict] = None,
    lemmy_platform: Optional[dict] = None,
    mastodon_platform: Optional[dict] = None,
    misskey_platform: Optional[dict] = None,
    pixelfed_platform: Optional[dict] = None,
    peertube_platform: Optional[dict] = None,
    mbin_platform: Optional[dict] = None,
) -> None:
    feeds = rss_feed_urls(html=page_html or "", base_url=base_url, har_path=har_path)
    page_hints = pagination_hints(html=page_html or "", base_url=base_url, har_path=har_path)
    audio_share = audio_share_signal(
        base_url=base_url,
        first_article_url=first_article_url,
        html_candidates=html_candidates,
        feeds=feeds,
        har_path=har_path,
    )
    # body_empty_likely summary — 본문이 본질적으로 없는 사이트 신호.
    # row_external_host (검색결과/aggregator) OR row_interactive_action (게임/투표/SPA) 중 하나라도 true 면 박힘.
    # LLM 한테 이 한 키만 보고 article.body_empty_acceptable=true 박으라고 시킴.
    body_empty_likely = bool(
        (row_external_host and float(row_external_host.get("external_ratio") or 0.0) >= 0.8)
        or (row_interactive_action and row_interactive_action.get("is_interactive_action"))
        or audio_share
    )
    # root_marketing_homepage — root 도메인 + nav/footer/dropdown/carousel 키워드 우세 + same-host
    # article rows 작음. register.py 가 LLM 전 fail-fast 게이트로 사용.
    root_marketing = root_marketing_homepage(
        base_url=base_url,
        html_candidates=html_candidates,
        nav_only_same_host=nav_only_same_host,
        body_empty_likely=body_empty_likely,
    )
    payload = {
        "html_repeating_patterns": html_candidates,
        "traffic_json_api_candidates": [
            {k: v for k, v in c.items() if k != "request_body_text"} for c in json_api_candidates
        ],
        "hydration_list_candidates": hydration_candidates,
        # 목록이 정적 HTML 행이 아니라 인라인 JS/JSON 안에 있을 때 (다음카페 모바일: articles.push({...}) 등). probe/hydration.extract_inline_data 산출.
        "inline_js_data_candidates": inline_js_candidates or [],
        # RSS/Atom URL 후보 — <link rel=alternate type=application/rss+xml|atom+xml>, HTML 본문 feed/rss 링크, HAR 의 XML feed 응답.
        # config writer 는 feed 후보가 있으면 list.url_template 에 이 URL 을 그대로 써야 한다.
        "rss_feed_urls": feeds,
        # URL pagination 후보 — 정적 HTML anchor 의 ?page=N + HAR XHR fetch URL 의 ?page=N.
        # Radiolab 류 SPA 가 ?page query 없으면 cards 안 그리는 사이트 봉합. config writer 는 hint
        # 발견 시 list.url_template 에 그대로 박고 list.pagination={kind:"query_param", page_param:<param>}.
        "pagination_hints": page_hints,
        # 페이지 HTML 안에 박힌 ID/슬러그 후보 — URL 에 없지만 사이트가 명시한 cafe_id/board_id 등.
        "runtime_id_candidates": runtime_ids or [],
        "first_article_url": first_article_url,
        # list row 들의 sample_url host 가 base host 와 다른 비율 — 검색결과/aggregator 검출.
        # None = 의미 있는 row 후보 0건; dict = {base_host, total_count, external_count, external_ratio, sample_external_urls}.
        "row_external_host": row_external_host,
        # list row 의 first_text 안 *액션 UI* 키워드 매칭 — 게임 디렉토리/투표/SPA 검출.
        # None = 매칭 0건; dict = {matched_row_count, matched_keyword_set, sample_row_first_text, is_interactive_action}.
        "row_interactive_action": row_interactive_action,
        # RSS item 의 link 가 share.transistor.fm 등 오디오 플레이어 host 를 가리키는 podcast feed.
        # 글 본문 HTML fetch 대상이 아니므로 article.body_empty_acceptable=true 로 완화한다.
        "audio_share_host_detected": audio_share,
        # 본문 없는 사이트 summary — row_external_host(>=0.8) OR row_interactive_action 둘 중 하나면 true.
        # LLM 이 이 키 보고 article.body_empty_acceptable=true 박음. retry 안 거치고 1st attempt 부터.
        "body_empty_likely": body_empty_likely,
        # 같은-host repeating pattern 이 *전부* nav/aside/header/footer 안 — single-article 페이지 신호.
        # board 페이지의 main list 는 nav 밖. nav-only 면 사이드바/topic-nav 만 잡힌 것 → 폴링 의미 없음.
        # None=의미 있는 same-host pattern 0건. dict={base_host, total_same_host, in_nav, outside_nav, nav_only_same_host, sample_nav_ancestors}.
        # register.py `_single_article_nav_only_check` 가 nav_only_same_host=true 면 board_shape 게이트 *전* 에 거부.
        "nav_only_same_host": nav_only_same_host,
        # 페이지가 자신이 *단일 article* 임을 선언한 명시 meta 신호 — og:type=article + schema.org NewsArticle/Article/... + microdata.
        # None=신호 0건. dict={has_og_article, schema_article_types, has_microdata_article, is_article_page, signals}.
        # register.py `_meta_article_diverging_check` 가 is_article_page=true AND first_article_url 의 path-prefix 가
        # input URL 과 *다르면* 거부 — 보드가 article 마크업 *우연히* 박은 사이트(omate 등)는 first_article 이 같은 path-prefix 라 통과.
        "article_meta_signals": article_meta_signals,
        # root 도메인 마케팅 랜딩/허브 페이지 검출 — board 정의 자체 X.
        # None=조건 미충족. dict={is_root_marketing_homepage, marketing_hits, marketing_selectors, total_same_host, body_empty_likely}.
        # 트리거: path='/' AND html_repeating_patterns top7 의 nav/footer/dropdown/carousel/swiper/menu 키워드 ≥ 2 AND same-host article rows ≤ 15.
        # register.py `_root_marketing_homepage_check` 가 LLM 호출 *전* REJECTED 마커 + 카테고리/섹션 URL 권장 메시지. learn=False.
        "root_marketing_homepage": root_marketing,
        # 정적 HTML 의 generator meta 로 Discourse 포럼 판정. None=Discourse 아님.
        # dict={is_discourse, base_url, version}. register.py 가 이 신호 보면 LLM 전 DiscourseAdapter
        # config 만들어 등록 시도 (fetch_list 빈 목록이면 일반 파이프라인 폴백).
        "wordpress_platform": wordpress_platform,
        "discourse_platform": discourse_platform,
        "common_platform": common_platform,
        "xenforo_platform": xenforo_platform,
        "medium_custom_domain": medium_custom_domain,
        "lemmy_platform": lemmy_platform,
        "mastodon_platform": mastodon_platform,
        "misskey_platform": misskey_platform,
        "pixelfed_platform": pixelfed_platform,
        "peertube_platform": peertube_platform,
        "mbin_platform": mbin_platform,
    }
    validate_payload("list_candidates.json", payload, allow_extra=False)
    (out_dir / "list_candidates.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
