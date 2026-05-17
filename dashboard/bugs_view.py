"""`/bugs` 라우트 — `.BUG.json` 마커 (코드 버그 / 시스템 측 결함) 관리.

dev box snapshot 기준 (`output/snapshot/poll_state/*.BUG.json`). 행 단위 Clear 버튼 (HTMX POST →
`scripts/remote.py clear-bug` → N100 의 `register.py --clear-bug` 호출). bug-fix workflow 마지막 step.

라우트:
  GET  /bugs              — 표
  POST /bugs/{slug}/clear — N100 의 `.BUG.json` 제거 (snapshot 도 동기)
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

from dashboard import control_actions as ctrl
from dashboard import state


_SLUG_RE = re.compile(r"^[A-Za-z0-9._%-]+$")


def _row_to_view(d: dict) -> dict[str, Any]:
    out = dict(d)
    reason = d.get("reason") or ""
    out["reason_short"] = (reason[:80] + "…") if len(reason) > 80 else reason
    url = d.get("url") or ""
    out["url_short"] = (url[:80] + "…") if len(url) > 80 else url
    out["last_at_short"] = (d.get("last_at") or "")[:19]
    out["first_at_short"] = (d.get("first_at") or "")[:19]
    out["tail_short"] = "\n".join((d.get("tail") or "").splitlines()[-6:])
    return out


def _snapshot_clear_bug(slug: str) -> bool:
    """snapshot 의 `<slug>.BUG.json` 도 제거 — N100 풀린 직후 dashboard 가 stale 안 보이게.
    실패 시 swallow (다음 pull 이 정정)."""
    paths = state.snapshot_paths()
    p = paths.state_dir / f"{slug}.BUG.json"
    if not p.exists():
        return False
    try:
        p.unlink()
        return True
    except OSError:
        return False


def register(app, templates, _render):
    @app.get("/bugs", response_class=HTMLResponse)
    async def bugs_page(request: Request):
        slugs = state.bug_slugs()
        rows = []
        for slug in slugs:
            d = state.bug_payload(slug) or {}
            d["slug"] = slug
            rows.append(_row_to_view(d))
        rows.sort(key=lambda r: r.get("last_at") or "", reverse=True)
        return _render("bugs.html", request, rows=rows, active="bugs")

    @app.post("/bugs/{slug}/clear", response_class=HTMLResponse)
    async def bugs_clear(request: Request, slug: str):
        if not _SLUG_RE.fullmatch(slug):
            raise HTTPException(status_code=400, detail="invalid slug")
        res = await ctrl.run_remote("clear-bug", slug)
        ok = bool(res.get("ok"))
        output = (res.get("output") or "").strip()
        snapshot_removed = False
        if "REMOVED" in output:
            snapshot_removed = _snapshot_clear_bug(slug)
        return templates.TemplateResponse(
            request, "_bugs_clear_result.html", {
                "slug": slug,
                "ok": ok,
                "output": output,
                "snapshot_removed": snapshot_removed,
            },
        )
