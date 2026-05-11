"""Phase 8: HAR에서 발견한 후보 API를 httpx로 재현 시도."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import httpx

from .signals import classify
from .types import Result


_DROP_REQUEST_HEADERS = {
    ":authority", ":method", ":path", ":scheme",
    "host", "content-length", "connection",
    "accept-encoding",  # httpx가 자동 처리
}


def replay_request(*, candidate: dict, out_dir: Path, idx: int) -> Result:
    method = (candidate.get("method") or "GET").upper()
    url = candidate.get("url") or ""
    raw_headers: dict[str, str] = candidate.get("request_headers") or {}
    body_text = candidate.get("request_body_text")

    headers = {k: v for k, v in raw_headers.items() if k.lower() not in _DROP_REQUEST_HEADERS and not k.startswith(":")}

    started = time.perf_counter()
    status: Optional[int] = None
    body: Optional[str] = None
    resp_headers: dict[str, str] = {}
    error: Optional[str] = None
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as c:
            if method == "GET":
                r = c.get(url, headers=headers)
            else:
                r = c.request(method, url, headers=headers, content=body_text)
            status = r.status_code
            body = r.text
            resp_headers = {k: v for k, v in r.headers.items()}
    except Exception as e:
        error = f"{type(e).__name__}: {e}"

    duration_ms = int((time.perf_counter() - started) * 1000)
    body_path: Optional[str] = None
    if body is not None:
        p = out_dir / f"replay_{idx}.body"
        p.write_text(body, encoding="utf-8", errors="replace")
        body_path = str(p)

    cls, notable = classify(status=status, body=body, headers=resp_headers, error=error)
    return Result(
        strategy=f"Replay#{idx}",
        target="replay",
        url=url,
        status=status,
        duration_ms=duration_ms,
        body_path=body_path,
        headers=resp_headers,
        classification=cls,
        notable=notable,
        error=error,
    )


def replay_all(candidates: list[dict], out_dir: Path) -> list[Result]:
    results: list[Result] = []
    for i, c in enumerate(candidates[:5]):  # 너무 많이 호출 방지
        results.append(replay_request(candidate=c, out_dir=out_dir, idx=i))
        time.sleep(2.0)
    summary = [r.to_dict() for r in results]
    (out_dir / "replay.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return results
