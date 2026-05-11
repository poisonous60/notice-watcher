"""Phase 5 — 유료 크롤링 API. 키가 환경변수/CLI 인자에 있을 때만 시도."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

from .signals import classify
from .types import Classification, Result


@dataclass
class PaidKeys:
    scraperapi: Optional[str] = None
    scrapingbee: Optional[str] = None
    zyte: Optional[str] = None
    brightdata_proxy: Optional[str] = None  # full proxy URL incl. credentials

    @classmethod
    def from_env_and_args(cls, args) -> "PaidKeys":
        return cls(
            scraperapi=getattr(args, "scraperapi_key", None) or os.environ.get("SCRAPERAPI_KEY"),
            scrapingbee=getattr(args, "scrapingbee_key", None) or os.environ.get("SCRAPINGBEE_KEY"),
            zyte=getattr(args, "zyte_key", None) or os.environ.get("ZYTE_API_KEY"),
            brightdata_proxy=getattr(args, "brightdata_proxy", None) or os.environ.get("BRIGHTDATA_PROXY_URL"),
        )


def _save(out_dir: Path, name: str, body: str) -> str:
    p = out_dir / f"s6p.{name}.html"
    p.write_text(body, encoding="utf-8", errors="replace")
    return str(p)


def _skipped(strategy: str, url: str, reason: str) -> Result:
    return Result(
        strategy=strategy,
        target="list",
        url=url,
        classification=Classification.METHOD_INCOMPATIBLE,
        notable=[reason],
    )


def try_scraperapi(*, url: str, key: Optional[str], out_dir: Path) -> Result:
    if not key:
        return _skipped("ScraperAPI", url, "no SCRAPERAPI_KEY")
    api = "http://api.scraperapi.com"
    params = {"api_key": key, "url": url, "render": "true", "country_code": "kr"}
    started = time.perf_counter()
    status, body, headers, error = None, None, {}, None
    try:
        with httpx.Client(timeout=60.0, follow_redirects=True) as c:
            r = c.get(api, params=params)
            status = r.status_code
            body = r.text
            headers = {k: v for k, v in r.headers.items()}
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    duration_ms = int((time.perf_counter() - started) * 1000)
    body_path = _save(out_dir, "scraperapi", body) if body is not None else None
    cls, notable = classify(status=status, body=body, headers=headers, error=error)
    return Result(
        strategy="ScraperAPI", target="list", url=url, status=status,
        duration_ms=duration_ms, body_path=body_path, headers=headers,
        classification=cls, notable=notable, error=error,
    )


def try_scrapingbee(*, url: str, key: Optional[str], out_dir: Path) -> Result:
    if not key:
        return _skipped("ScrapingBee", url, "no SCRAPINGBEE_KEY")
    api = "https://app.scrapingbee.com/api/v1/"
    params = {"api_key": key, "url": url, "render_js": "true", "country_code": "kr"}
    started = time.perf_counter()
    status, body, headers, error = None, None, {}, None
    try:
        with httpx.Client(timeout=60.0, follow_redirects=True) as c:
            r = c.get(api, params=params)
            status = r.status_code
            body = r.text
            headers = {k: v for k, v in r.headers.items()}
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    duration_ms = int((time.perf_counter() - started) * 1000)
    body_path = _save(out_dir, "scrapingbee", body) if body is not None else None
    cls, notable = classify(status=status, body=body, headers=headers, error=error)
    return Result(
        strategy="ScrapingBee", target="list", url=url, status=status,
        duration_ms=duration_ms, body_path=body_path, headers=headers,
        classification=cls, notable=notable, error=error,
    )


def try_zyte(*, url: str, key: Optional[str], out_dir: Path) -> Result:
    if not key:
        return _skipped("Zyte", url, "no ZYTE_API_KEY")
    api = "https://api.zyte.com/v1/extract"
    started = time.perf_counter()
    status, body, headers, error = None, None, {}, None
    try:
        with httpx.Client(timeout=60.0, auth=(key, "")) as c:
            r = c.post(api, json={"url": url, "browserHtml": True})
            status = r.status_code
            try:
                data = r.json()
                body = data.get("browserHtml") or data.get("httpResponseBody") or r.text
            except Exception:
                body = r.text
            headers = {k: v for k, v in r.headers.items()}
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    duration_ms = int((time.perf_counter() - started) * 1000)
    body_path = _save(out_dir, "zyte", body) if body is not None else None
    cls, notable = classify(status=status, body=body, headers=headers, error=error)
    return Result(
        strategy="Zyte", target="list", url=url, status=status,
        duration_ms=duration_ms, body_path=body_path, headers=headers,
        classification=cls, notable=notable, error=error,
    )


def try_brightdata(*, url: str, proxy: Optional[str], out_dir: Path) -> Result:
    if not proxy:
        return _skipped("BrightData", url, "no BRIGHTDATA_PROXY_URL")
    started = time.perf_counter()
    status, body, headers, error = None, None, {}, None
    try:
        with httpx.Client(
            timeout=60.0,
            follow_redirects=True,
            proxy=proxy,
            verify=False,  # Bright Data Web Unlocker는 자체 CA를 쓰는 경우가 많음
        ) as c:
            r = c.get(url)
            status = r.status_code
            body = r.text
            headers = {k: v for k, v in r.headers.items()}
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    duration_ms = int((time.perf_counter() - started) * 1000)
    body_path = _save(out_dir, "brightdata", body) if body is not None else None
    cls, notable = classify(status=status, body=body, headers=headers, error=error)
    return Result(
        strategy="BrightData", target="list", url=url, status=status,
        duration_ms=duration_ms, body_path=body_path, headers=headers,
        classification=cls, notable=notable, error=error,
    )


def try_all_paid(*, url: str, keys: PaidKeys, out_dir: Path) -> list[Result]:
    return [
        try_scraperapi(url=url, key=keys.scraperapi, out_dir=out_dir),
        try_scrapingbee(url=url, key=keys.scrapingbee, out_dir=out_dir),
        try_zyte(url=url, key=keys.zyte, out_dir=out_dir),
        try_brightdata(url=url, proxy=keys.brightdata_proxy, out_dir=out_dir),
    ]
