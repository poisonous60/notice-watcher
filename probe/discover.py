"""Phase 6: RSS/Atom + robots.txt + sitemap 디스커버리."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from .headers import preset_h2_chrome_min


_FEED_PATHS = ("/rss", "/feed", "/atom.xml", "/rss.xml", "/feed.xml", "/feeds")


def discover_feeds(*, page_url: str, page_html: str, out_dir: Path) -> dict:
    """페이지 head에서 alternate 피드 + 관용 경로 추측."""
    candidates: list[dict] = []

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
    with httpx.Client(headers=headers, timeout=10.0, follow_redirects=True) as client:
        for path in _FEED_PATHS:
            url = urljoin(base, path)
            try:
                r = client.get(url)
                if r.status_code == 200 and ("xml" in (r.headers.get("content-type", "")).lower()
                                             or r.text.lstrip().startswith("<?xml")):
                    candidates.append({
                        "source": "well-known-path",
                        "url": url,
                        "status": r.status_code,
                        "content_type": r.headers.get("content-type"),
                        "size": len(r.text),
                    })
            except Exception:
                continue
            time.sleep(0.5)

    out = {"page_url": page_url, "candidates": candidates}
    (out_dir / "feed_candidates.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out


_CRAWL_DELAY_RE = re.compile(r"^\s*crawl-delay\s*:\s*(\d+(?:\.\d+)?)", re.IGNORECASE | re.MULTILINE)


def read_robots(*, page_url: str, out_dir: Path) -> dict:
    parts = urlsplit(page_url)
    url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    info = {"url": url, "status": None, "crawl_delay": None, "disallow": [], "raw_path": None}
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
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {e}"

    (out_dir / "robots.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return info
