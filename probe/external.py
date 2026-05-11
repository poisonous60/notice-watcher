"""Phase 5 (외부 변환): Jina Reader / Firecrawl / Crawl4AI."""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import Optional

import httpx

from .signals import classify
from .types import Classification, Result


def try_jina(*, url: str, out_dir: Path, baseline_blocked: bool = False) -> Result:
    """Jina Reader: 키 불필요, 1줄 마크다운 변환."""
    proxy_url = f"https://r.jina.ai/{url}"
    started = time.perf_counter()
    status: Optional[int] = None
    body: Optional[str] = None
    error: Optional[str] = None
    resp_headers: dict[str, str] = {}

    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            r = client.get(proxy_url)
            status = r.status_code
            body = r.text
            resp_headers = {k: v for k, v in r.headers.items()}
    except Exception as e:
        error = f"{type(e).__name__}: {e}"

    duration_ms = int((time.perf_counter() - started) * 1000)
    body_path: Optional[str] = None
    if body is not None:
        p = out_dir / "jina.md"
        p.write_text(body, encoding="utf-8", errors="replace")
        body_path = str(p)

    cls, notable = classify(
        status=status, body=body, headers=resp_headers, error=error, baseline_blocked=baseline_blocked,
    )
    return Result(
        strategy="Jina",
        target="list",
        url=proxy_url,
        status=status,
        duration_ms=duration_ms,
        body_path=body_path,
        headers=resp_headers,
        classification=cls,
        notable=notable,
        error=error,
    )


_FIRECRAWL_KEY_RE = re.compile(r'api_key\s*=\s*"([^"]+)"')


def _detect_firecrawl_key(project_root: Path) -> Optional[str]:
    """환경변수 또는 reference/Firecrwal_snippet.py(루트 fallback)에서 키 자동 발견."""
    env_key = os.environ.get("FIRECRAWL_API_KEY")
    if env_key:
        return env_key
    candidates = [
        project_root / "reference" / "Firecrwal_snippet.py",
        project_root / "reference" / "firecrawl_snippet.py",
        project_root / "Firecrwal_snippet.py",  # legacy
    ]
    for snippet in candidates:
        if snippet.exists():
            try:
                txt = snippet.read_text(encoding="utf-8")
                m = _FIRECRAWL_KEY_RE.search(txt)
                if m:
                    return m.group(1)
            except Exception:
                continue
    return None


def try_firecrawl(*, url: str, out_dir: Path, project_root: Path, baseline_blocked: bool = False) -> Result:
    """Firecrawl scrape. 키 자동 발견(Firecrwal_snippet.py 또는 FIRECRAWL_API_KEY)."""
    key = _detect_firecrawl_key(project_root)
    started = time.perf_counter()
    if not key:
        return Result(
            strategy="Firecrawl",
            target="list",
            url=url,
            classification=Classification.METHOD_INCOMPATIBLE,
            notable=["no FIRECRAWL_API_KEY"],
        )

    try:
        from firecrawl import Firecrawl  # type: ignore
    except ImportError:
        return Result(
            strategy="Firecrawl",
            target="list",
            url=url,
            classification=Classification.METHOD_INCOMPATIBLE,
            notable=["firecrawl-py not installed"],
        )

    body: Optional[str] = None
    error: Optional[str] = None
    status: Optional[int] = None
    notable_extra: list[str] = []
    try:
        app = Firecrawl(api_key=key)
        result = app.scrape(url)
        # firecrawl-py >= 1.x: 결과 객체. markdown/html/links 등이 있을 수 있음.
        md = None
        if hasattr(result, "markdown"):
            md = getattr(result, "markdown", None)
        elif isinstance(result, dict):
            md = result.get("markdown") or result.get("data", {}).get("markdown")
        body = md or json.dumps(
            result if isinstance(result, dict) else getattr(result, "__dict__", {"_repr": repr(result)}),
            default=str,
            ensure_ascii=False,
            indent=2,
        )
        status = 200
        notable_extra.append(f"markdown {len(body or '')} chars")
    except Exception as e:
        error = f"{type(e).__name__}: {e}"

    duration_ms = int((time.perf_counter() - started) * 1000)
    body_path = None
    if body is not None:
        p = out_dir / "firecrawl.md"
        p.write_text(body, encoding="utf-8", errors="replace")
        body_path = str(p)

    cls, notable = classify(
        status=status, body=body, headers={}, error=error, baseline_blocked=baseline_blocked,
    )
    notable.extend(notable_extra)
    return Result(
        strategy="Firecrawl",
        target="list",
        url=url,
        status=status,
        duration_ms=duration_ms,
        body_path=body_path,
        classification=cls,
        notable=notable,
        error=error,
    )


def try_crawl4ai(*, url: str, out_dir: Path, baseline_blocked: bool = False) -> Result:
    """Crawl4AI AsyncWebCrawler.arun(url). OSS, 키 불필요."""
    try:
        from crawl4ai import AsyncWebCrawler  # type: ignore
    except ImportError:
        return Result(
            strategy="Crawl4AI",
            target="list",
            url=url,
            classification=Classification.METHOD_INCOMPATIBLE,
            notable=["crawl4ai not installed"],
        )

    started = time.perf_counter()
    body: Optional[str] = None
    html: Optional[str] = None
    error: Optional[str] = None
    status: Optional[int] = None
    notable_extra: list[str] = []

    async def _run():
        async with AsyncWebCrawler() as crawler:
            return await crawler.arun(url=url)

    try:
        result = asyncio.run(_run())
        body = getattr(result, "markdown", None)
        html = getattr(result, "cleaned_html", None) or getattr(result, "html", None)
        if isinstance(body, dict):
            body = body.get("raw_markdown") or body.get("markdown") or json.dumps(body, ensure_ascii=False)
        status = 200 if (body or html) else None
        if body:
            notable_extra.append(f"markdown {len(body)} chars")
        if html:
            notable_extra.append(f"cleaned_html {len(html)} chars")
        links = getattr(result, "links", None)
        if isinstance(links, dict):
            internal = len(links.get("internal", []) or [])
            external = len(links.get("external", []) or [])
            notable_extra.append(f"links internal={internal} external={external}")
    except Exception as e:
        error = f"{type(e).__name__}: {e}"

    duration_ms = int((time.perf_counter() - started) * 1000)
    body_path: Optional[str] = None
    if body is not None:
        (out_dir / "crawl4ai.md").write_text(body, encoding="utf-8", errors="replace")
        body_path = str(out_dir / "crawl4ai.md")
    if html is not None:
        (out_dir / "crawl4ai.html").write_text(html, encoding="utf-8", errors="replace")

    cls, notable = classify(
        status=status, body=body or html, headers={}, error=error, baseline_blocked=baseline_blocked,
    )
    notable.extend(notable_extra)
    return Result(
        strategy="Crawl4AI",
        target="list",
        url=url,
        status=status,
        duration_ms=duration_ms,
        body_path=body_path,
        classification=cls,
        notable=notable,
        error=error,
    )
