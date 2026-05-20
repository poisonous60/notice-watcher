"""Phase 6: RSS/Atom + robots.txt + sitemap 디스커버리."""
from __future__ import annotations

import gzip
import json
import re
import zlib
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET

import httpx
from bs4 import BeautifulSoup

from ._contract import validate_payload
from .headers import preset_h2_chrome_min


_FEED_PATHS = ("/rss", "/feed", "/atom.xml", "/rss.xml", "/feed.xml", "/feeds")

# 입력 URL 자체가 RSS/Atom 피드인 경우 path 매칭. catalog 의
# `bbs.ruliweb.com/news/board/<id>/rss` / `steamcommunity.com/.../rss/` /
# `*/feeds/news.xml` / `*.atom` 류 — 기존 `_FEED_PATHS` 는 호스트 *루트* 에서만
# 관용 경로 시도라 board-별 RSS path 를 못 잡았음. board_shape 게이트의 false-positive
# 거부 원인 (2026-05-19 catalog batch 분포).
_FEED_URL_RE = re.compile(
    r"(?i)(?:/rss/?|/feed/?|/feeds(?:/|$)|\.rss|\.atom|\.xml)(?:[?#]|$)"
)


def _looks_like_feed_url(url: str) -> bool:
    """입력 URL path 가 RSS/Atom 피드 모양인지 (board_shape gate 우회 + discover_feeds self-include)."""
    try:
        path_with_query = urlsplit(url).path + ("?" + urlsplit(url).query if urlsplit(url).query else "")
    except ValueError:
        return False
    return bool(_FEED_URL_RE.search(path_with_query))


def _body_is_feed(text: str) -> bool:
    """fetch 한 page 본문이 RSS/Atom/RDF 피드인지 (URL path 모양 무관 content-sniff).

    `_looks_like_feed_url` 는 path 휴리스틱 — `hnrss.org/newest`(피드 토큰 없음)·
    `phoronix.com/rss.php`(rss 뒤 `.php`)·`gamespot.com/feeds/news/`(`/feeds/` 뒤 path 계속)
    류 직접-피드 URL 을 못 잡음. 그런데 page_html 자체가 RSS XML → 본문 root 태그로 검출하면
    path 모양과 무관하게 board_shape false-reject 회피 (2026-05-20-b batch).
    """
    head = (text or "").lstrip()[:1024].lower()
    if not head.startswith("<?xml") and not head.startswith("<rss") \
            and not head.startswith("<feed") and not head.startswith("<rdf"):
        return False
    return ("<rss" in head) or ("<feed" in head) or ("<rdf" in head and "rss" in head)


def discover_feeds(*, page_url: str, page_html: str, out_dir: Path) -> dict:
    """페이지 head에서 alternate 피드 + 관용 경로 추측 + 입력 URL 자체 feed 검출."""
    candidates: list[dict] = []

    # 입력 URL 자체가 feed path 면 1st candidate 로 박는다 — `_board_shape_check` 가
    # feed_candidates 비어있지 않음을 보드 시그널로 인정하므로 게이트 통과 보장.
    # path 모양(url) 또는 본문 content-sniff(html) 둘 중 하나라도 feed 면 박음.
    if _looks_like_feed_url(page_url):
        candidates.append({
            "source": "input-url-feed-path",
            "url": page_url,
        })
    elif _body_is_feed(page_html):
        candidates.append({
            "source": "input-url-feed-content",
            "url": page_url,
        })

    soup = BeautifulSoup(page_html or "", "lxml")
    for link in soup.select('link[rel="alternate"]'):
        t = (link.get("type") or "").lower()
        if "rss" in t or "atom" in t or "xml" in t:
            href = link.get("href", "")
            if href:
                candidates.append({
                    "source": "head-alternate",
                    "type": link.get("type"),
                    "title": link.get("title"),
                    "url": urljoin(page_url, href),
                })

    parts = urlsplit(page_url)
    base = f"{parts.scheme}://{parts.netloc}"
    headers = preset_h2_chrome_min()

    # 6 well-known feed path 동시 fetch — probe 는 일회성 정찰이라 host 폴라이트 0.5s 의미 약함.
    def _try(path: str) -> dict | None:
        url = urljoin(base, path)
        try:
            with httpx.Client(headers=headers, timeout=10.0, follow_redirects=True) as client:
                r = client.get(url)
            if r.status_code == 200 and ("xml" in (r.headers.get("content-type", "")).lower()
                                         or r.text.lstrip().startswith("<?xml")):
                return {
                    "source": "well-known-path",
                    "url": url,
                    "status": r.status_code,
                    "content_type": r.headers.get("content-type"),
                    "size": len(r.text),
                }
        except Exception:
            return None
        return None

    from concurrent.futures import ThreadPoolExecutor as _TPE
    with _TPE(max_workers=len(_FEED_PATHS)) as _ex:
        for hit in _ex.map(_try, _FEED_PATHS):
            if hit is not None:
                candidates.append(hit)

    out = {"page_url": page_url, "candidates": candidates}
    validate_payload("feed_candidates.json", out, allow_extra=False)
    (out_dir / "feed_candidates.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out


_CRAWL_DELAY_RE = re.compile(r"^\s*crawl-delay\s*:\s*(\d+(?:\.\d+)?)", re.IGNORECASE | re.MULTILINE)
_SITEMAP_LINE_RE = re.compile(r"(?im)^\s*sitemap\s*:\s*(\S+)\s*$")


def read_robots(*, page_url: str, out_dir: Path) -> dict:
    parts = urlsplit(page_url)
    url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    info: dict = {
        "url": url, "status": None, "crawl_delay": None,
        "disallow": [], "sitemaps": [], "raw_path": None,
    }
    try:
        with httpx.Client(headers=preset_h2_chrome_min(), timeout=10.0, follow_redirects=True) as c:
            r = c.get(url)
            info["status"] = r.status_code
            if r.status_code == 200:
                txt = r.text
                p = out_dir / "robots.txt"
                p.write_text(txt, encoding="utf-8", errors="replace")
                info["raw_path"] = str(p)
                m = _CRAWL_DELAY_RE.search(txt)
                if m:
                    info["crawl_delay"] = float(m.group(1))
                info["disallow"] = [
                    line.split(":", 1)[1].strip()
                    for line in txt.splitlines()
                    if line.lower().startswith("disallow:")
                ][:30]
                info["sitemaps"] = _SITEMAP_LINE_RE.findall(txt)[:10]
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {e}"

    validate_payload("robots.json", info, allow_extra=False)
    (out_dir / "robots.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return info


# --------------------------------------------------------------------------- #
# sitemap.xml discovery — robots 의 Sitemap: 라인 + 표준 경로 (/sitemap.xml 등)
# 재귀 sitemapindex + gzip + namespace 유무 둘 다 + byte cap (gzip bomb 방어)
# --------------------------------------------------------------------------- #

_SITEMAP_DEFAULT_PATHS = ("/sitemap.xml", "/sitemap_index.xml", "/sitemap.xml.gz")
_MAX_SITEMAP_DEPTH = 2
_MAX_SITEMAP_URLS = 500
_MAX_SITEMAP_BYTES = 10 * 1024 * 1024  # 10 MB 본문/decompressed 상한
_MAX_OUT_TOTAL = 100  # digest 에 들어갈 cap

# board page URL 우선순위 휴리스틱 (cap 자를 때 살리기 위함).
_BOARD_KEYWORDS = ("notice", "bbs", "board", "news", "article", "post", "공지", "게시판", "뉴스", "글")
_BOARD_ID_RE = re.compile(r"[?&](?:id|no|page|p|bid|cid|board)=", re.I)


def fetch_sitemaps(*, page_url: str, robots_sitemaps: list, out_dir: Path) -> dict:
    """robots 의 Sitemap: 라인 (있으면) + 표준 경로 폴백 → sitemap.xml 재귀 fetch+parse.

    사용자가 board root 아닌 URL 던졌을 때 후보 회복 신호 (`config_writer.system.txt`
    의 `discovery.sitemap_candidates` 참조). probe Phase 6 — 항상 도는 정찰, retry X.

    fail-soft (네트워크/파싱 오류 → 빈 list). digest 에 *항상* 박힘 — generate 가 i==1 부터 참조.
    """
    info: dict = {
        "page_url": page_url,
        "sitemap_urls_tried": [],
        "candidates": [],  # board-like 점수 내림차순. {url, score}
        "stats": {"sitemap_count": 0, "fetched": 0, "errors": 0, "out_total": 0},
        "error": None,
    }
    try:
        parts = urlsplit(page_url)
        if not parts.scheme or not parts.netloc:
            info["error"] = "bad page_url"
            _write(out_dir, info)
            return info
        origin_host = parts.netloc.lower()
        allowed_hosts: set = {origin_host}
        root_url = f"{parts.scheme}://{parts.netloc}"

        headers = preset_h2_chrome_min()
        with httpx.Client(headers=headers, timeout=10.0, follow_redirects=True) as client:
            # 1) seed = robots 의 Sitemap 라인. 빈 list 면 표준 경로 폴백 (HEAD 또는 Range GET).
            seeds: list[str] = list(robots_sitemaps or [])
            if not seeds:
                for path in _SITEMAP_DEFAULT_PATHS:
                    cand = urljoin(root_url, path)
                    if _head_exists(client, cand):
                        seeds.append(cand)
                        break
            info["sitemap_urls_tried"] = seeds[:5]
            info["stats"]["sitemap_count"] = len(info["sitemap_urls_tried"])

            # 2) sitemap parse (재귀)
            collected: list[str] = []
            for sm in info["sitemap_urls_tried"]:
                got = _parse_sitemap_recursive(client, sm, depth=0, stats=info["stats"])
                collected.extend(got)
                if len(collected) >= _MAX_SITEMAP_URLS:
                    break

        # 3) host filter (origin + redirect canonical 둘 다 허용) + dedup + 정규화
        seen: set = set()
        normalized: list[str] = []
        for u in collected:
            norm = _normalize_url(u)
            if not norm or norm in seen:
                continue
            try:
                if urlsplit(norm).netloc.lower() not in allowed_hosts:
                    continue
            except ValueError:
                continue
            seen.add(norm)
            normalized.append(norm)

        # 4) board-like 점수 정렬, cap
        scored = [{"url": u, "score": _board_like_score(u)} for u in normalized]
        scored.sort(key=lambda d: d["score"], reverse=True)
        info["candidates"] = scored[:_MAX_OUT_TOTAL]
        info["stats"]["out_total"] = len(info["candidates"])
    except Exception as e:  # noqa: BLE001
        info["error"] = f"{type(e).__name__}: {e}"

    _write(out_dir, info)
    return info


def _write(out_dir: Path, info: dict) -> None:
    validate_payload("sitemap.json", info, allow_extra=False)
    (out_dir / "sitemap.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _head_exists(client: httpx.Client, url: str) -> bool:
    try:
        r = client.head(url)
        if r.status_code < 400:
            return True
        if r.status_code in (405, 501, 403):
            r2 = client.get(url, headers={"Range": "bytes=0-1023"})
            return r2.status_code < 400
        return False
    except (httpx.HTTPError, OSError):
        return False


def _parse_sitemap_recursive(client: httpx.Client, sm_url: str, depth: int,
                              stats: dict) -> list[str]:
    if depth > _MAX_SITEMAP_DEPTH:
        return []
    try:
        r = client.get(sm_url)
        if r.status_code != 200:
            stats["errors"] = stats.get("errors", 0) + 1
            return []
        body = r.content[:_MAX_SITEMAP_BYTES]
        stats["fetched"] = stats.get("fetched", 0) + 1
    except (httpx.HTTPError, OSError):
        stats["errors"] = stats.get("errors", 0) + 1
        return []

    if sm_url.endswith(".gz") or body[:2] == b"\x1f\x8b":
        try:
            body = _gzip_decompress_capped(body)
        except (OSError, gzip.BadGzipFile, EOFError, ValueError, zlib.error):
            stats["errors"] = stats.get("errors", 0) + 1
            return []

    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        stats["errors"] = stats.get("errors", 0) + 1
        return []

    tag = _strip_ns(root.tag)
    out: list[str] = []
    if tag == "sitemapindex":
        for child in root:
            if _strip_ns(child.tag) != "sitemap":
                continue
            loc = _child_text(child, "loc")
            if loc:
                out.extend(_parse_sitemap_recursive(client, loc.strip(), depth + 1, stats))
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
    return out


def _child_text(el, local_name: str) -> Optional[str]:
    for child in el:
        if _strip_ns(child.tag) == local_name:
            return (child.text or "").strip() or None
    return None


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _gzip_decompress_capped(data: bytes) -> bytes:
    """gzip bomb 방어 — decompressed cap."""
    decomp = zlib.decompressobj(zlib.MAX_WBITS | 16)
    out = bytearray()
    out.extend(decomp.decompress(data, _MAX_SITEMAP_BYTES))
    if not decomp.eof and len(out) >= _MAX_SITEMAP_BYTES:
        raise ValueError("gzip decompressed size exceeds cap")
    return bytes(out)


def _normalize_url(u: str) -> Optional[str]:
    try:
        p = urlsplit(u.strip())
    except ValueError:
        return None
    if not p.scheme or not p.netloc:
        return None
    path = p.path or "/"
    return f"{p.scheme.lower()}://{p.netloc.lower()}{path}" + (f"?{p.query}" if p.query else "")


def _board_like_score(u: str) -> int:
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
        s += 1
    depth = len([seg for seg in (p.path or "").split("/") if seg])
    if 1 <= depth <= 3:
        s += 1
    return s
