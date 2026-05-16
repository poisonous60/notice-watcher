"""`/learned` 라우트 — 자동 학습된 거부 패턴 (`output/learned_blacklist.json`) 관리.

dev box snapshot 기준 (`output/snapshot/learned_blacklist.json` — scripts/inspect_subs.py pull 이 떨굼).
검색 (host/path/reason/slug LIKE) + 행 단위 unlearn 버튼 (HTMX POST → scripts/remote.py unlearn → N100
의 register.py --unlearn 호출 → atomic write). Pull 안 했으면 빈 페이지.

라우트:
  GET  /learned                  — 표 + 검색
  POST /learned/{pattern_id}/unlearn — N100 의 learned_blacklist 에서 entry 제거 (snapshot 도 동기)
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

from dashboard import control_actions as ctrl
from dashboard import state


_PATTERN_ID_RE = re.compile(r"^[a-f0-9]{1,12}$")


def _learned_path():
    return state.SNAPSHOT_DIR / "learned_blacklist.json"


def _load_patterns() -> list[dict]:
    p = _learned_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    patterns = data.get("patterns")
    if not isinstance(patterns, list):
        return []
    return [p for p in patterns if isinstance(p, dict) and p.get("id")]


def _filter(patterns: list[dict], q: Optional[str]) -> list[dict]:
    """검색어 q (소문자 substring) 가 host_suffix / path_prefix / last_reason / last_url / last_slug 중 어디든 매치."""
    if not q:
        return patterns
    ql = q.strip().lower()
    if not ql:
        return patterns
    out = []
    for p in patterns:
        hay = " ".join(str(p.get(k) or "") for k in
                       ("host_suffix", "path_prefix", "last_reason", "last_url", "last_slug", "id"))
        if ql in hay.lower():
            out.append(p)
    return out


def _sort(patterns: list[dict]) -> list[dict]:
    """last_rejected_at 내림차순 — 최근 거부 위로."""
    return sorted(patterns, key=lambda p: str(p.get("last_rejected_at") or ""), reverse=True)


def _row_to_view(p: dict) -> dict[str, Any]:
    d = dict(p)
    reason = d.get("last_reason") or ""
    d["reason_short"] = (reason[:80] + "…") if len(reason) > 80 else reason
    url = d.get("last_url") or ""
    d["url_short"] = (url[:80] + "…") if len(url) > 80 else url
    d["last_rejected_at_short"] = (d.get("last_rejected_at") or "")[:19]
    d["first_rejected_at_short"] = (d.get("first_rejected_at") or "")[:19]
    return d


def _snapshot_unlearn(pattern_id: str) -> bool:
    """snapshot 파일에서도 entry 제거 — N100 에서 풀린 직후 dashboard 가 stale 표 안 보여주려고.
    실패해도 swallow (다음 pull 이 정정). 돌려준 bool = 제거됐는지."""
    p = _learned_path()
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return False
    patterns = (data.get("patterns") if isinstance(data, dict) else None) or []
    new = [x for x in patterns if not (isinstance(x, dict) and x.get("id") == pattern_id)]
    if len(new) == len(patterns):
        return False
    data["patterns"] = new
    try:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return False
    return True


def register(app, templates, _render):
    """`dashboard/app.py` 에서 호출 — 라우트 등록."""

    @app.get("/learned", response_class=HTMLResponse)
    async def learned_page(request: Request, q: Optional[str] = None):
        all_patterns = _load_patterns()
        filtered = _sort(_filter(all_patterns, q))
        rows = [_row_to_view(p) for p in filtered]
        stats = {
            "total": len(all_patterns),
            "shown": len(rows),
            "total_rejects": sum(int(p.get("reject_count") or 0) for p in all_patterns),
        }
        return _render(
            "learned.html", request,
            rows=rows,
            stats=stats,
            cur={"q": q or ""},
            active="learned",
        )

    @app.post("/learned/{pattern_id}/unlearn", response_class=HTMLResponse)
    async def learned_unlearn(request: Request, pattern_id: str):
        # path traversal / injection 차단 — 형식 검증.
        if not _PATTERN_ID_RE.fullmatch(pattern_id):
            raise HTTPException(status_code=400, detail="invalid pattern_id")
        res = await ctrl.run_remote("unlearn", pattern_id)
        ok = bool(res.get("ok"))
        ctrl_output = (res.get("output") or "").strip()
        # N100 에서 풀렸으면 snapshot 도 동기 — Pull 안 기다리고 즉시 표 사라지게.
        snapshot_removed = False
        if "REMOVED" in ctrl_output:
            snapshot_removed = _snapshot_unlearn(pattern_id)
        return templates.TemplateResponse(
            request, "_learned_unlearn_result.html", {
                "pattern_id": pattern_id,
                "ok": ok,
                "output": ctrl_output,
                "snapshot_removed": snapshot_removed,
            },
        )
