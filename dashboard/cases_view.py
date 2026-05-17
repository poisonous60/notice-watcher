"""`/cases` 라우트 — skill 실행 audit (`output/cases.sqlite3` 의 `case_runs`).

dev box 전용. N100 안 봄. `docs/case_runs DB 계획.md` rev 2 구현.

라우트:
  GET /cases           — 표 + 필터 (skill / outcome / fix_layer / failure_key / requested_by / 기간)
  GET /cases/<slug>/md — 해당 slug 의 docs/cases/<slug>.md 본문 렌더 (path traversal 가드)
"""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from bot.case_runs_meta import OUTCOMES, OUTCOME_LABELS, escape_like
from dashboard import state

try:
    import markdown as _markdown
except ImportError:  # dev box 의존성 (`requirements-dashboard.txt`) 미설치 시 graceful
    _markdown = None

_MD_EXTENSIONS = ["fenced_code", "tables", "sane_lists", "toc", "nl2br"]


def _render_markdown(body: str) -> Optional[str]:
    """case .md 본문 → HTML. markdown lib 없으면 None (템플릿이 raw fallback)."""
    if _markdown is None:
        return None
    return _markdown.markdown(body, extensions=_MD_EXTENSIONS, output_format="html5")


def _row_to_view(row) -> dict[str, Any]:
    """sqlite Row → 템플릿 친화 dict (JSON 필드 unpack + md 파일 존재 확인)."""
    d = dict(row)
    for jcol in ("failure_keys", "files_changed"):
        raw = d.get(jcol)
        if raw:
            try:
                d[jcol] = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                d[jcol] = [raw]
        else:
            d[jcol] = []
    d["outcome_label"] = OUTCOME_LABELS.get(d.get("outcome") or "", d.get("outcome") or "")
    reason = d.get("reason") or ""
    d["reason_short"] = (reason[:120] + "…") if len(reason) > 120 else reason
    md_slug = d.get("case_md_slug")
    d["case_md_exists"] = bool(md_slug and state.cases_md_path(md_slug) is not None)
    return d


def _build_filter_sql(
    skill: Optional[str],
    outcome: Optional[str],
    layer: Optional[str],
    failure_key: Optional[str],
    requested_by: Optional[str],
    q: Optional[str],
    period_days: Optional[int],
    *,
    limit: int = 500,
    offset: int = 0,
) -> tuple[str, list[Any]]:
    """LIKE 패턴은 escape_like + ESCAPE '\\\\' — 사용자 input 의 `_`/`%` wildcard 화 차단."""
    sql = "SELECT * FROM case_runs WHERE 1=1"
    params: list[Any] = []
    if skill:
        sql += " AND skill = ?"
        params.append(skill)
    if outcome:
        sql += " AND outcome = ?"
        params.append(outcome)
    if layer:
        sql += " AND fix_layer LIKE ? ESCAPE '\\'"
        params.append(f"%{escape_like(layer)}%")
    if failure_key:
        # JSON array 안 정확 키 매칭 (substring 충돌 회피)
        sql += " AND failure_keys LIKE ? ESCAPE '\\'"
        params.append(f'%"{escape_like(failure_key)}"%')
    if requested_by:
        sql += " AND requested_by = ?"
        params.append(requested_by)
    if q:
        like = f"%{escape_like(q)}%"
        sql += " AND (slug LIKE ? ESCAPE '\\' OR url LIKE ? ESCAPE '\\' OR reason LIKE ? ESCAPE '\\')"
        params.extend([like, like, like])
    if period_days and period_days > 0:
        sql += f" AND ts > datetime('now', '-{int(period_days)} days')"
    sql += " ORDER BY ts DESC LIMIT ? OFFSET ?"
    params.extend([int(limit), int(offset)])
    return sql, params


def _distinct(conn, column: str) -> list[str]:
    """`case_runs` 의 distinct 컬럼 값. NULL/빈 제외."""
    rows = conn.execute(
        f"SELECT DISTINCT {column} FROM case_runs WHERE {column} IS NOT NULL AND {column} != '' ORDER BY {column}"
    ).fetchall()
    return [r[0] for r in rows]


def _stats(conn) -> dict[str, Any]:
    """간단 stats — outcome 분포 / fix_layer top / files prefix top.
    total < 30 이면 show=False (의미 없는 통계 회피)."""
    total = conn.execute("SELECT COUNT(*) FROM case_runs").fetchone()[0]
    if total < 30:
        return {"total": total, "show": False}

    out = conn.execute(
        "SELECT outcome, COUNT(*) c FROM case_runs GROUP BY outcome ORDER BY c DESC"
    ).fetchall()
    layer = conn.execute(
        "SELECT fix_layer, COUNT(*) c FROM case_runs WHERE fix_layer IS NOT NULL GROUP BY fix_layer ORDER BY c DESC LIMIT 5"
    ).fetchall()

    return {
        "total": total,
        "show": True,
        "outcome_dist": [(r[0], r[1]) for r in out],
        "layer_top": [(r[0], r[1]) for r in layer],
    }


def register(app, templates, _render):
    """`dashboard/app.py` 에서 호출 — 라우트 등록."""

    @app.get("/cases", response_class=HTMLResponse)
    async def cases_page(
        request: Request,
        skill: Optional[str] = None,
        outcome: Optional[str] = None,
        layer: Optional[str] = None,
        failure_key: Optional[str] = None,
        requested_by: Optional[str] = None,
        q: Optional[str] = None,
        period: int = Query(0, ge=0, le=3650),
        page: int = Query(1, ge=1),
        page_size: int = Query(100, ge=10, le=500),
    ):
        conn = state.open_cases_conn()
        if conn is None:
            return _render("cases_empty.html", request, active="cases")
        try:
            offset = (page - 1) * page_size
            sql, params = _build_filter_sql(
                skill, outcome, layer, failure_key, requested_by, q, period,
                limit=page_size + 1, offset=offset,
            )
            raw_rows = conn.execute(sql, params).fetchall()
            has_next = len(raw_rows) > page_size
            rows = [_row_to_view(r) for r in raw_rows[:page_size]]
            distinct_outcomes = set(_distinct(conn, "outcome"))
            facets = {
                "skills": _distinct(conn, "skill"),
                # OUTCOMES 순서대로 (가독성), DB 에 실제 있는 것만
                "outcomes": [o for o in OUTCOMES if o in distinct_outcomes],
                "layers": _distinct(conn, "fix_layer"),
            }
            stats = _stats(conn)
        finally:
            conn.close()
        return _render(
            "cases.html", request,
            rows=rows,
            facets=facets,
            stats=stats,
            cur={
                "skill": skill, "outcome": outcome, "layer": layer,
                "failure_key": failure_key, "requested_by": requested_by,
                "q": q, "period": period,
            },
            page=page, has_next=has_next, page_size=page_size,
            active="cases",
        )

    @app.get("/cases/{slug}/md", response_class=HTMLResponse)
    async def cases_md(request: Request, slug: str):
        # state.cases_md_path 가 safe_slug + CASES_DIR 안 모두 검사
        p = state.cases_md_path(slug)
        if p is None:
            raise HTTPException(status_code=404, detail="case .md 없음 또는 slug 안전 X")
        body = p.read_text(encoding="utf-8").lstrip("﻿")
        body_html = _render_markdown(body)
        return _render(
            "case_md.html", request,
            slug=slug, body=body, body_html=body_html, active="cases",
        )
