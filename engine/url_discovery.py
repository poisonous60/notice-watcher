"""URL discovery — 사용자가 부정확한 URL (도메인 root 등) 던졌을 때 후보 board page list 회복.

직접 구현 (sitemap.xml + a[href] crawl). prior-art 조사 (`docs/2026-05-18-prior-art-조사.md` §3a +
followup-plan Action #1) 의 Firecrawl `/map` API 대체.

소스:
1. robots.txt 의 `Sitemap:` 라인 (RFC 9309)
2. 표준 sitemap.xml (gzip + 재귀 sitemapindex, namespace 유무 둘 다 지원)
3. seed page HTML 의 `<a href>` (same-host 만 — canonical redirect host 도 허용)

dedup + host filter + board-like 우선순위 정렬 + cap. 의존 = httpx + bs4 (기존 deps).
네트워크 fail = 빈 list (always returns list).

bench 라이브 (`docs/2026-05-18-prior-art-조사.md` §3a):
- `cse.skku.edu/` → 15 entry (`/cse/notice.do` 포함)
- `gamemeca.com` → 11 entry (`/news.php` 포함)
- `cafe.naver.com/gutterlife` → 1 entry (iframe/login — 한계)
"""
from __future__ import annotations

import gzip
import json
import re
import time
import zlib
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
_LOG_PATH = ROOT / "output" / "url_discovery_log.json"

_DEFAULT_TIMEOUT = 10.0
_MAX_TOTAL = 100
_MAX_PER_PAGE_CRAWL = 50
_MAX_SITEMAP_DEPTH = 2  # urlset → sitemapindex → urlset (3 단계까지)
_MAX_SITEMAP_URLS = 500  # 한 sitemap 에서 추출 cap
_MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MB 본문/sitemap 상한 (gzip bomb 방어)
_MAX_LOG_LINES = 1000  # log file rotation 기준

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def discover_board_candidates(url: str, *, timeout: float = _DEFAULT_TIMEOUT,
                              log: bool = True) -> list[str]:
    """seed URL → 후보 internal URL list. 3 source (robots / sitemap / a[href]) 합쳐 dedup.

    fail-soft: 네트워크 오류 / 파싱 실패 → 가능한 만큼만, 또는 빈 list. always returns list.
    """
    started = time.monotonic()
    try:
        parts = urlsplit(url)
        if not parts.scheme or not parts.netloc:
            if log:
                _append_log({"url": url, "ts": _now(), "status": "bad_url",
                             "count": 0, "latency_ms": 0})
            return []
    except ValueError:
        if log:
            _append_log({"url": url, "ts": _now(), "status": "bad_url",
                         "count": 0, "latency_ms": 0})
        return []

    origin_host = parts.netloc.lower()
    allowed_hosts: set[str] = {origin_host}
    root_url = urlunsplit((parts.scheme, parts.netloc, "/", "", ""))

    sources: dict[str, int] = {"robots_sitemaps": 0, "default_sitemap": 0, "page_crawl": 0}

    with httpx.Client(
        timeout=timeout,
        headers={"User-Agent": _UA, "Accept-Language": "ko-KR,en;q=0.8"},
        follow_redirects=True,
    ) as client:
        # 1) robots.txt — Sitemap: 라인 + canonical host 추출
        robots_sitemaps, robots_final_host = _fetch_robots_sitemaps(client, root_url)
        if robots_final_host:
            allowed_hosts.add(robots_final_host)

        # 2) 표준 sitemap.xml 경로 (robots 에 안 박혀 있을 때 폴백)
        default_sitemaps: list[str] = []
        if not robots_sitemaps:
            for path in ("/sitemap.xml", "/sitemap_index.xml", "/sitemap.xml.gz"):
                cand = urljoin(root_url, path)
                if _head_exists(client, cand):
                    default_sitemaps.append(cand)
                    break

        # 3) sitemap parse (재귀)
        sitemap_links: list[str] = []
        for sm in (robots_sitemaps + default_sitemaps)[:5]:  # cap 5 sitemap
            sitemap_links.extend(_parse_sitemap_recursive(client, sm, depth=0))
            if len(sitemap_links) >= _MAX_SITEMAP_URLS:
                break
        sources["robots_sitemaps"] = len(robots_sitemaps)
        sources["default_sitemap"] = len(sitemap_links)

        # 4) seed page a[href] (final URL 의 host 도 allowed_hosts 에 합침 — canonical redirect 대응)
        page_links, page_final_host = _crawl_page_anchors(client, url)
        if page_final_host:
            allowed_hosts.add(page_final_host)
        sources["page_crawl"] = len(page_links)

    # combine + dedup, host filter (origin + canonical redirect 둘 다 OK)
    seen: set[str] = set()
    out: list[str] = []
    for u in sitemap_links + page_links:
        norm = _normalize_url(u)
        if not norm or norm in seen:
            continue
        try:
            if urlsplit(norm).netloc.lower() not in allowed_hosts:
                continue
        except ValueError:
            continue
        seen.add(norm)
        out.append(norm)

    # board-like 우선순위 정렬 (cap 자를 때 board URL 살림)
    out.sort(key=_board_like_score, reverse=True)
    out = out[:_MAX_TOTAL]

    latency = int((time.monotonic() - started) * 1000)
    if log:
        _append_log({"url": url, "ts": _now(), "status": "ok",
                     "count": len(out), "latency_ms": latency,
                     "sources": sources, "hosts": sorted(allowed_hosts)})
    return out


# ---- board-like 우선순위 -------------------------------------------------- #

_BOARD_KEYWORDS = (
    "notice", "bbs", "board", "news", "article", "post",
    "공지", "게시판", "뉴스", "글",
)
_BOARD_ID_RE = re.compile(r"[?&](?:id|no|page|p|bid|cid|board)=", re.I)


def _board_like_score(u: str) -> int:
    """board URL 점수 — 높을수록 board page 가능성. cap 자를 때 우선순위."""
    try:
        p = urlsplit(u)
    except ValueError:
        return 0
    s = 0
    path_q = (p.path or "").lower() + "?" + (p.query or "")
    for kw in _BOARD_KEYWORDS:
        if kw in path_q:
            s += 3
            break
    if _BOARD_ID_RE.search("?" + (p.query or "")):
        s += 2
    if re.search(r"/\d{3,}(?:/|$)", p.path or ""):
        s += 1  # /board/123/ 형태
    # 짧은 path 우대 (홈/메뉴 보다 sub-path 가 board 일 확률 ↑ 단 너무 깊어도 X)
    depth = len([seg for seg in (p.path or "").split("/") if seg])
    if 1 <= depth <= 3:
        s += 1
    return s


# ---- robots.txt ------------------------------------------------------------ #

_SITEMAP_RE = re.compile(r"(?im)^\s*sitemap\s*:\s*(\S+)\s*$")


def _fetch_robots_sitemaps(client: httpx.Client, root_url: str) -> tuple[list[str], Optional[str]]:
    """robots.txt 의 Sitemap: 라인 list + final URL 의 host (canonical redirect 반영)."""
    try:
        r = client.get(urljoin(root_url, "/robots.txt"))
        if r.status_code != 200:
            return [], None
        text = _read_body_capped(r)
        final_host = (r.url.host or "").lower() or None
    except (httpx.HTTPError, OSError):
        return [], None
    return _SITEMAP_RE.findall(text or ""), final_host


# ---- sitemap.xml ----------------------------------------------------------- #

def _head_exists(client: httpx.Client, url: str) -> bool:
    """HEAD 보내고 200 면 True. 일부 서버는 HEAD 거부 → GET 폴백."""
    try:
        r = client.head(url)
        if r.status_code < 400:
            return True
        # HEAD 거부 (405/403/501) → GET 작게
        if r.status_code in (405, 501, 403):
            r2 = client.get(url, headers={"Range": "bytes=0-1023"})
            return r2.status_code < 400
        return False
    except (httpx.HTTPError, OSError):
        return False


def _parse_sitemap_recursive(client: httpx.Client, sm_url: str, depth: int) -> list[str]:
    if depth > _MAX_SITEMAP_DEPTH:
        return []
    try:
        r = client.get(sm_url)
        if r.status_code != 200:
            return []
        body = _read_body_capped_bytes(r)
    except (httpx.HTTPError, OSError):
        return []

    # gzip auto (.gz suffix 또는 magic bytes) — decompress 시 cap 한 번 더 (gzip bomb 방어)
    if sm_url.endswith(".gz") or body[:2] == b"\x1f\x8b":
        try:
            body = _gzip_decompress_capped(body)
        except (OSError, gzip.BadGzipFile, EOFError, ValueError, zlib.error):
            return []

    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []

    tag = _strip_ns(root.tag)
    out: list[str] = []
    if tag == "sitemapindex":
        # 재귀 — 안 sitemap.xml 들. namespace 유무 둘 다 지원.
        for child in root:
            if _strip_ns(child.tag) != "sitemap":
                continue
            loc = _child_text(child, "loc")
            if loc:
                out.extend(_parse_sitemap_recursive(client, loc.strip(), depth + 1))
                if len(out) >= _MAX_SITEMAP_URLS:
                    return out[:_MAX_SITEMAP_URLS]
    elif tag == "urlset":
        for child in root:
            if _strip_ns(child.tag) != "url":
                continue
            loc = _child_text(child, "loc")
            if loc:
                out.append(loc.strip())
                if len(out) >= _MAX_SITEMAP_URLS:
                    return out
    # else: 알 수 없는 root — skip
    return out


def _child_text(el, local_name: str) -> Optional[str]:
    """namespace 유무 둘 다 매치 — local name 만 보고 첫 매칭 element 의 text."""
    for child in el:
        if _strip_ns(child.tag) == local_name:
            return (child.text or "").strip() or None
    return None


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


# ---- page a[href] ---------------------------------------------------------- #

def _crawl_page_anchors(client: httpx.Client, url: str) -> tuple[list[str], Optional[str]]:
    """seed page → a[href] list + final URL host (canonical redirect 반영)."""
    try:
        r = client.get(url)
        if r.status_code != 200:
            return [], None
        html = _read_body_capped(r)
        base_url = str(r.url)
        final_host = (r.url.host or "").lower() or None
    except (httpx.HTTPError, OSError):
        return [], None

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:  # noqa: BLE001
        return [], final_host

    out: list[str] = []
    seen_local: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        try:
            absu = urljoin(base_url, href)
        except ValueError:
            continue
        if absu in seen_local:
            continue
        seen_local.add(absu)
        out.append(absu)
        if len(out) >= _MAX_PER_PAGE_CRAWL:
            break
    return out, final_host


# ---- byte caps (gzip bomb / 거대 sitemap 방어) --------------------------- #

def _read_body_capped(r: httpx.Response) -> str:
    raw = _read_body_capped_bytes(r)
    enc = r.encoding or "utf-8"
    try:
        return raw.decode(enc, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return raw.decode("utf-8", errors="replace")


def _read_body_capped_bytes(r: httpx.Response) -> bytes:
    raw = r.content
    if len(raw) > _MAX_RESPONSE_BYTES:
        raw = raw[:_MAX_RESPONSE_BYTES]
    return raw


def _gzip_decompress_capped(data: bytes) -> bytes:
    """gzip decompress 결과 cap — bomb 방어 (1 MB gzip → 100 MB plain 같은 케이스)."""
    # zlib.decompressobj 에 wbits=MAX_WBITS|16 = gzip header 자동 인식.
    decomp = zlib.decompressobj(zlib.MAX_WBITS | 16)
    out = bytearray()
    out.extend(decomp.decompress(data, _MAX_RESPONSE_BYTES))
    if not decomp.eof and len(out) >= _MAX_RESPONSE_BYTES:
        raise ValueError("gzip decompressed size exceeds cap")
    return bytes(out)


# ---- helpers --------------------------------------------------------------- #

def _normalize_url(u: str) -> Optional[str]:
    """fragment 제거 + 후행 / 정리. query 는 유지 (board URL 흔히 ?id=)."""
    try:
        p = urlsplit(u.strip())
    except ValueError:
        return None
    if not p.scheme or not p.netloc:
        return None
    path = p.path or "/"
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, p.query, ""))


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _append_log(entry: dict) -> None:
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _maybe_rotate_log()
    except OSError:
        pass


def _maybe_rotate_log() -> None:
    """log line 수 _MAX_LOG_LINES 넘으면 최근 절반만 보존 (in-place rewrite)."""
    try:
        with _LOG_PATH.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) <= _MAX_LOG_LINES:
            return
        keep = lines[-(_MAX_LOG_LINES // 2):]
        with _LOG_PATH.open("w", encoding="utf-8") as f:
            f.writelines(keep)
    except OSError:
        pass


# ---- CLI ------------------------------------------------------------------- #

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python -m engine.url_discovery <url>", file=sys.stderr)
        raise SystemExit(2)
    seed = sys.argv[1]
    cands = discover_board_candidates(seed)
    print(f"[url_discovery] {len(cands)} candidates")
    for c in cands[:50]:
        print(f"  {c}")
