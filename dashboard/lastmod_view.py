"""`/lastmod` 라우트 — sitemap lastmod observe-only 로그 (ADR 0013 A 묶음).

`output/sitemap_lastmod_log.jsonl` 의 매 poll cycle append line 을 표/agg 로.
1주 운영 후 sitemap-skip 활성화 trigger (false_skip_pct < 1% / wasted_fetch_pct > 30% /
coverage ≥ 30%) 만족 여부 확인용. 본 dashboard 가 evidence 표시 — 활성화 판단은 사용자.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse

from dashboard import state


_TAIL_DEFAULT = 200
_TAIL_MAX = 2000


def _read_lines(path, *, tail: int) -> tuple[list[dict], int]:
    """JSONL → list[dict] (마지막 tail 줄). total line count 도 반환.

    JSONL 은 append-only — 파일 끝에서 tail*2 bytes 정도 읽고 line split 하면 보통 충분하지만,
    여기서는 단순 풀-read (~수 MB 까지 fast). 1년 후 GB 단위 되면 별 작업으로 rotation.
    """
    if not path.exists():
        return [], 0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return [], 0
    total = sum(1 for ln in lines if ln.strip())
    out: list[dict] = []
    for ln in lines[-tail:]:
        s = ln.strip()
        if not s:
            continue
        try:
            d = json.loads(s)
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out, total


def _aggregate(rows: list[dict]) -> dict[str, Any]:
    """slug 별 집계 — coverage / would_skip / wasted_fetch / sitemap_index 비율 + 전체 KPI.

    coverage = current_lastmod 가 None 아닌 row 비율
    false_skip_pct = would_skip=True 면서 fetch_list_n_new > 0 비율 (skip 했으면 새 글 놓침)
    wasted_fetch_pct = would_skip=False 면서 fetch_list_n_new = 0 비율 (skip 했어도 됐는데 안 함)
    """
    n_total = len(rows)
    n_cov = sum(1 for r in rows if r.get("current_lastmod"))
    n_skip = sum(1 for r in rows if r.get("would_skip"))
    n_index = sum(1 for r in rows if r.get("is_sitemap_index"))
    n_error = sum(1 for r in rows if (r.get("lastmod_source") or "") == "error")
    n_false_skip = sum(1 for r in rows
                       if r.get("would_skip") and int(r.get("fetch_list_n_new") or 0) > 0)
    n_wasted = sum(1 for r in rows
                   if not r.get("would_skip") and int(r.get("fetch_list_n_new") or 0) == 0
                   and r.get("current_lastmod") and r.get("prev_lastmod"))
    n_compared = sum(1 for r in rows if r.get("current_lastmod") and r.get("prev_lastmod"))

    def _pct(num: int, den: int) -> float:
        return (100.0 * num / den) if den else 0.0

    per_slug: dict[str, dict] = defaultdict(lambda: {
        "n": 0, "n_cov": 0, "n_skip": 0, "n_index": 0, "n_error": 0,
        "n_compared": 0, "n_false_skip": 0, "n_wasted": 0,
        "last_ts": "", "sitemap_url": "",
    })
    for r in rows:
        slug = r.get("slug") or "?"
        p = per_slug[slug]
        p["n"] += 1
        if r.get("current_lastmod"):
            p["n_cov"] += 1
        if r.get("would_skip"):
            p["n_skip"] += 1
        if r.get("is_sitemap_index"):
            p["n_index"] += 1
        if (r.get("lastmod_source") or "") == "error":
            p["n_error"] += 1
        if r.get("current_lastmod") and r.get("prev_lastmod"):
            p["n_compared"] += 1
            if r.get("would_skip") and int(r.get("fetch_list_n_new") or 0) > 0:
                p["n_false_skip"] += 1
            if not r.get("would_skip") and int(r.get("fetch_list_n_new") or 0) == 0:
                p["n_wasted"] += 1
        ts = r.get("ts") or ""
        if ts > p["last_ts"]:
            p["last_ts"] = ts
            p["sitemap_url"] = r.get("sitemap_url") or p["sitemap_url"]

    slug_rows = []
    for slug, p in per_slug.items():
        slug_rows.append({
            "slug": slug,
            "n": p["n"],
            "coverage_pct": _pct(p["n_cov"], p["n"]),
            "skip_pct": _pct(p["n_skip"], p["n"]),
            "index_pct": _pct(p["n_index"], p["n"]),
            "error_pct": _pct(p["n_error"], p["n"]),
            "false_skip_pct": _pct(p["n_false_skip"], p["n_compared"]),
            "wasted_fetch_pct": _pct(p["n_wasted"], p["n_compared"]),
            "n_compared": p["n_compared"],
            "last_ts": p["last_ts"][:19],
            "sitemap_url": p["sitemap_url"],
        })
    slug_rows.sort(key=lambda r: (-r["n"], r["slug"]))

    return {
        "n_total": n_total,
        "n_slugs": len(per_slug),
        "coverage_pct": _pct(n_cov, n_total),
        "skip_pct": _pct(n_skip, n_total),
        "index_pct": _pct(n_index, n_total),
        "error_pct": _pct(n_error, n_total),
        "false_skip_pct": _pct(n_false_skip, n_compared),
        "wasted_fetch_pct": _pct(n_wasted, n_compared),
        "n_compared": n_compared,
        "slug_rows": slug_rows,
    }


def _row_to_view(d: dict) -> dict[str, Any]:
    out = dict(d)
    out["ts_short"] = (d.get("ts") or "")[:19]
    cur = d.get("current_lastmod") or ""
    prev = d.get("prev_lastmod") or ""
    out["current_short"] = cur[:32]
    out["prev_short"] = prev[:32]
    out["sitemap_url_short"] = (d.get("sitemap_url") or "")[:80]
    out["error_short"] = ((d.get("error") or "")[:80])
    return out


def register(app, templates, _render):  # noqa: ARG001
    @app.get("/lastmod", response_class=HTMLResponse)
    async def lastmod_page(request: Request,
                           tail: int = _TAIL_DEFAULT,
                           slug: str | None = None):
        tail = max(10, min(int(tail or _TAIL_DEFAULT), _TAIL_MAX))
        if slug is not None and not state.safe_slug(slug):
            slug = None
        path = state.lastmod_log_path()
        rows, total = _read_lines(path, tail=tail)
        if slug:
            rows = [r for r in rows if r.get("slug") == slug]
        agg = _aggregate(rows)
        view_rows = [_row_to_view(r) for r in reversed(rows)]
        return _render("lastmod.html", request,
                       active="lastmod",
                       present=path.exists(),
                       total=total,
                       tail=tail,
                       slug_filter=slug or "",
                       agg=agg,
                       rows=view_rows,
                       log_path=str(path))
