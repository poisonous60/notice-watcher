"""Firecrawl `/map` 통합 — 사용자가 부정확한 URL (도메인 root 등) 던졌을 때 후보 board page list 회복.

prior-art 조사 (`docs/2026-05-18-prior-art-조사.md` §3a + followup-plan Action #1) 결과:
- `https://cse.skku.edu/` → 15 internal entry (`/cse/notice.do` 포함 ✅)
- `https://www.gamemeca.com` → 11 entry (`/news.php` ✅)
- iframe / login-walled (naver cafe 등) → 1 entry 만 (한계)

사용 자리: `scripts/register.py` 의 generate FAIL 직후 (probe 산출 `posts_nonempty` 류). probe 자체엔 안 들어감
(`bot/url_gate.py` 와 책임 분리 — gate 는 정책/SSRF 만).

비용: 1 credit / request. hosted free tier = 500 credit/월. 키 미설정 시 fail-soft (return []).

API: POST https://api.firecrawl.dev/v1/map  (Firecrawl v1)
  body: {"url": "<seed>", "limit": 50, "includeSubdomains": false}
  response: {"success": true, "links": ["url1", ...]}

로그: output/firecrawl_map_log.json — append 모드 (디버깅 / credit 추적).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import httpx

ROOT = Path(__file__).resolve().parent.parent
_LOG_PATH = ROOT / "output" / "firecrawl_map_log.json"

_API_URL = "https://api.firecrawl.dev/v1/map"
_DEFAULT_TIMEOUT = 10.0
_DEFAULT_LIMIT = 50


def discover_board_candidates(
    url: str,
    api_key: str,
    *,
    timeout: float = _DEFAULT_TIMEOUT,
    limit: int = _DEFAULT_LIMIT,
    log: bool = True,
) -> list[str]:
    """Firecrawl `/map` 호출 → internal link + sitemap.xml entry list 반환.

    fail-soft: 키 없음 / 네트워크 오류 / 비정상 응답 → 빈 list. 로깅만 함.
    """
    if not (api_key or "").strip():
        if log:
            _append_log({"url": url, "ts": _now(), "status": "no_key", "count": 0, "latency_ms": 0})
        return []

    started = time.monotonic()
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(
                _API_URL,
                headers={
                    "Authorization": f"Bearer {api_key.strip()}",
                    "Content-Type": "application/json",
                },
                json={"url": url, "limit": limit, "includeSubdomains": False},
            )
    except (httpx.HTTPError, OSError) as e:
        latency = int((time.monotonic() - started) * 1000)
        if log:
            _append_log({"url": url, "ts": _now(), "status": "http_error",
                         "error": str(e)[:200], "count": 0, "latency_ms": latency})
        return []

    latency = int((time.monotonic() - started) * 1000)
    if r.status_code != 200:
        if log:
            _append_log({"url": url, "ts": _now(), "status": f"http_{r.status_code}",
                         "count": 0, "latency_ms": latency})
        return []

    try:
        body = r.json()
    except (json.JSONDecodeError, ValueError):
        if log:
            _append_log({"url": url, "ts": _now(), "status": "bad_json",
                         "count": 0, "latency_ms": latency})
        return []

    if not isinstance(body, dict) or not body.get("success"):
        if log:
            _append_log({"url": url, "ts": _now(), "status": "api_fail",
                         "error": str(body.get("error") or "")[:200],
                         "count": 0, "latency_ms": latency})
        return []

    links = body.get("links") or []
    candidates: list[str] = []
    seen: set[str] = set()
    for link in links:
        if not isinstance(link, str):
            continue
        link = link.strip()
        if link and link not in seen:
            seen.add(link)
            candidates.append(link)

    if log:
        _append_log({"url": url, "ts": _now(), "status": "ok",
                     "count": len(candidates), "latency_ms": latency,
                     "credit": 1})
    return candidates


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _append_log(entry: dict) -> None:
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


if __name__ == "__main__":
    import os
    import sys

    if len(sys.argv) < 2:
        print("usage: python -m engine.url_discovery <url>", file=sys.stderr)
        raise SystemExit(2)

    seed = sys.argv[1]
    key = os.environ.get("FIRECRAWL_API_KEY", "").strip()
    if not key:
        print("[url_discovery] FIRECRAWL_API_KEY env 없음 — fail-soft 로 빈 list 반환", file=sys.stderr)

    cands = discover_board_candidates(seed, key)
    print(f"[url_discovery] {len(cands)} candidates")
    for c in cands[:30]:
        print(f"  {c}")
