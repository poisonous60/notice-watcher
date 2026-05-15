"""FastAPI app + all routes.

Owner 1인용·localhost 한정·인증 0. 페이지 네비게이션은 일반 링크, HTMX 는 액션(Pull/Fetch) 과
부분 갱신용으로만 씀.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import html as _html

import jinja2
from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from bot import db, inspector
from dashboard import actions as act
from dashboard import prompts, state
from dashboard import usage_view
from dashboard import user_view
from dashboard import control_actions as ctrl
from dashboard import tracing_view

HERE = Path(__file__).resolve().parent
# autoescape 명시: Starlette/FastAPI 버전에 따라 default 가 바뀔 수 있어 직접 Environment 주입.
# .env / SSH stdout 등 외부 텍스트가 템플릿으로 들어오므로 autoescape OFF 는 즉시 XSS.
_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(HERE / "templates")),
    autoescape=jinja2.select_autoescape(default_for_string=True, default=True),
)
templates = Jinja2Templates(env=_jinja_env)


def _is_http_url(value: object) -> bool:
    """`href={{ url }}` 에 박기 전 안전한 http(s) 스킴인지 확인. `javascript:`·`data:` 등 차단."""
    if not isinstance(value, str):
        return False
    return value.startswith("http://") or value.startswith("https://")


templates.env.filters["is_http"] = _is_http_url
templates.env.globals["is_http_url"] = _is_http_url

app = FastAPI(title="notice-watcher dashboard", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")


# --------------------------------------------------------------------------- #
# DI
# --------------------------------------------------------------------------- #
def get_conn():
    """sqlite 커넥션을 yield 한 뒤 finally 로 close — 핸들러에서 예외나도 fd 안 샘."""
    conn = state.open_conn()
    try:
        yield conn
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def require_slug(slug: str) -> str:
    """경로 path 로 받은 slug 가 안전한지 검사. 어긋나면 404 — 파일시스템 traversal 차단."""
    if not state.safe_slug(slug):
        raise HTTPException(status_code=404, detail="invalid slug")
    return slug


# --------------------------------------------------------------------------- #
# 템플릿 헬퍼 — Starlette 1.0 의 TemplateResponse(request, name, context) 시그니처에 맞춤
# --------------------------------------------------------------------------- #
def _render(name: str, request: Request, *, status_code: int = 200, **extra: Any) -> HTMLResponse:
    ctx: dict[str, Any] = {
        "snapshot_ts": state.last_pull_str(),
        "snapshot_present": state.snapshot_exists(),
    }
    ctx.update(extra)
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def _partial(name: str, request: Request, **extra: Any) -> HTMLResponse:
    """HTMX 부분 응답 — base 컨텍스트(sidebar/snapshot_ts) 안 씀."""
    return templates.TemplateResponse(request, name, extra)


def _no_snapshot(request: Request) -> HTMLResponse:
    return _render("no_snapshot.html", request)


# --------------------------------------------------------------------------- #
# Triage (홈)
# --------------------------------------------------------------------------- #
@app.get("/", response_class=HTMLResponse)
async def triage_page(request: Request, conn=Depends(get_conn)):
    if conn is None:
        return _no_snapshot(request)
    paths = state.snapshot_paths()
    summary = inspector.triage_summary(conn, paths)
    rows = inspector.recent_jobs(conn, limit=15)
    quick_prompts = {
        "report_triage_bulk": prompts.report_triage_bulk(
            report_ids=[r["id"] for r in db.list_reports(conn, status="open", limit=200)]
        ) if summary["open_reports"] > 0 else None,
        "hand_config_triage": prompts.hand_config_triage_queue(
            failed_slugs=summary["failed_slugs"]
        ) if summary["failed_slugs"] else None,
    }
    return _render("triage.html", request,
                   summary=summary, recent=rows, quick=quick_prompts, active="triage")


# --------------------------------------------------------------------------- #
# Jobs
# --------------------------------------------------------------------------- #
@app.get("/jobs", response_class=HTMLResponse)
async def jobs_list(request: Request, count: int = Query(50, ge=1, le=200),
                    status: Optional[str] = None, q: Optional[str] = None,
                    conn=Depends(get_conn)):
    if conn is None:
        return _no_snapshot(request)
    rows = inspector.recent_jobs(conn, limit=count)
    if status:
        rows = [r for r in rows if (r.get("status") or "") == status]
    if q:
        ql = q.strip().lower()
        def _match(r):
            if ql in (r.get("slug") or "").lower():
                return True
            if ql in (r.get("url") or "").lower():
                return True
            rb = r.get("requested_by") or {}
            if isinstance(rb, dict) and ql in str(rb.get("name") or "").lower():
                return True
            return False
        rows = [r for r in rows if _match(r)]
    return _render("jobs.html", request,
                   rows=rows, count=count, filter_status=status, q=q, active="jobs")


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: int, conn=Depends(get_conn)):
    if conn is None:
        return _no_snapshot(request)
    paths = state.snapshot_paths()
    result = inspector.inspect(conn, paths, job_id=job_id)
    if result is None:
        return HTMLResponse("<p>잡 없음.</p>", status_code=404)
    j = result.latest_job or {}
    fail_reason = None
    if j.get("status") in ("error", "failed") or (j.get("result_rc") not in (None, 0)):
        tail = (j.get("result_tail") or "").strip().splitlines()
        fail_reason = tail[-1][:200] if tail else f"status={j.get('status')} rc={j.get('result_rc')}"
    p_handconfig = prompts.hand_config_for_url(
        url=j.get("url") or "",
        slug=result.slug,
        fail_reason=fail_reason,
        job_id=job_id,
    )
    return _render("job_detail.html", request,
                   result=result, job=j, p_handconfig=p_handconfig, active="jobs")


# --------------------------------------------------------------------------- #
# Subs (slug 기준)
# --------------------------------------------------------------------------- #
@app.get("/subs", response_class=HTMLResponse)
async def subs_list(request: Request, q: Optional[str] = None,
                    conn=Depends(get_conn)):
    if conn is None:
        return _no_snapshot(request)
    paths = state.snapshot_paths()
    slugs = state.unique_slugs(conn)
    rows = []
    for s in slugs:
        subs = db.subscriptions_for_slug(conn, s)
        cfg_path = paths.configs_dir / f"{s}.json"
        st_path = paths.state_dir / f"{s}.json"
        failed_marker = paths.state_dir / f"{s}.FAILED.json"
        broken = 0
        if st_path.exists():
            try:
                d = json.loads(st_path.read_text(encoding="utf-8"))
                broken = int(d.get("consecutive_breakage", 0) or 0)
            except (OSError, json.JSONDecodeError):
                pass
        # 검색 노출용 user_id 목록 (중복 제거)
        user_ids = sorted({str(s_row["user_id"]) for s_row in subs})
        rows.append({
            "slug": s,
            "n_subs": len(subs),
            "has_config": cfg_path.exists(),
            "has_state": st_path.exists(),
            "failed": failed_marker.exists(),
            "broken": broken,
            "sample_url": (subs[0]["url"] if subs else None),
            "user_ids": user_ids,
        })
    rows.sort(key=lambda r: (-r["broken"], not r["failed"], r["slug"]))
    if q:
        ql = q.strip().lower()
        def _match(r):
            if ql in r["slug"].lower():
                return True
            if ql in (r.get("sample_url") or "").lower():
                return True
            if any(ql in u.lower() for u in r["user_ids"]):
                return True
            return False
        rows = [r for r in rows if _match(r)]
    return _render("subs.html", request, rows=rows, q=q, active="subs")


@app.get("/subs/{slug}", response_class=HTMLResponse)
async def sub_detail(request: Request, slug: str = Depends(require_slug),
                     conn=Depends(get_conn)):
    if conn is None:
        return _no_snapshot(request)
    paths = state.snapshot_paths()
    result = inspector.inspect(conn, paths, slug=slug)
    if result is None:
        return HTMLResponse(f"<p>slug <code>{_html.escape(slug)}</code> 없음.</p>", status_code=404)
    failed_payload = state.failed_payload(slug)
    sample_url = None
    if result.subscriptions:
        sample_url = result.subscriptions[0].get("url")
    elif result.latest_job:
        sample_url = result.latest_job.get("url")
    p_redo = prompts.hand_config_redo_slug(slug=slug, url=sample_url)
    p_diag = prompts.diagnose_slug(slug=slug)
    return _render("sub_detail.html", request,
                   result=result, slug=slug, failed=failed_payload,
                   p_redo=p_redo, p_diag=p_diag, active="subs")


# --------------------------------------------------------------------------- #
# Users (person-entity 페이지)
# --------------------------------------------------------------------------- #
# 자유 입력 user_id / target_id 검증 — Discord snowflake 형식만 허용.
import re as _re
_USER_ID_RE = _re.compile(r"^[0-9]{1,32}$")


def require_user_id(user_id: str) -> str:
    if not _USER_ID_RE.match(user_id or ""):
        raise HTTPException(status_code=404, detail="invalid user_id")
    return user_id


_SORT_DIRECTIONS = ("asc", "desc")


@app.get("/users", response_class=HTMLResponse)
async def users_list(request: Request,
                     q: Optional[str] = None,
                     slug: Optional[str] = None,
                     open_report: int = Query(0),
                     has_feedback: int = Query(0),
                     has_channel: int = Query(0),
                     sort: str = Query("last_active"),
                     direction: str = Query("desc"),
                     conn=Depends(get_conn)):
    if conn is None:
        return _no_snapshot(request)
    if slug and not state.safe_slug(slug):
        raise HTTPException(status_code=400, detail="invalid slug")
    if direction not in _SORT_DIRECTIONS:
        direction = "desc"
    rows = user_view.collect(
        conn,
        q=q, slug_filter=slug,
        chip_open_report=bool(open_report),
        chip_has_feedback=bool(has_feedback),
        chip_has_channel=bool(has_channel),
        sort=sort, direction=direction,
    )
    # slug autocomplete dropdown 옵션
    all_slugs = state.unique_slugs(conn)
    return _render("users.html", request,
                   rows=rows, q=q, slug_filter=slug,
                   open_report=bool(open_report),
                   has_feedback=bool(has_feedback),
                   has_channel=bool(has_channel),
                   sort=sort, direction=direction,
                   all_slugs=all_slugs, active="users")


@app.get("/users/{user_id}", response_class=HTMLResponse)
async def user_detail(request: Request,
                      user_id: str = Depends(require_user_id),
                      conn=Depends(get_conn)):
    if conn is None:
        return _no_snapshot(request)
    u = user_view.detail(conn, user_id)
    if u is None:
        return HTMLResponse(
            f"<p>user <code>{_html.escape(user_id)}</code> 없음.</p>",
            status_code=404,
        )
    # seen_post_ids 경고는 expand 시 partial(`/users/{id}/deliveries`)이 알아서 계산 — 여기서 풀스캔 안 함.
    return _render("user_detail.html", request, user=u, active="users")


@app.get("/users/{user_id}/deliveries", response_class=HTMLResponse)
async def user_deliveries_inline(request: Request,
                                 user_id: str = Depends(require_user_id),
                                 slug: str = Query(...),
                                 conn=Depends(get_conn)):
    """HTMX expandable — 한 (user, slug) 의 deliveries 최근 50."""
    if conn is None:
        return HTMLResponse("(snapshot 없음)", status_code=503)
    if not state.safe_slug(slug):
        raise HTTPException(status_code=400, detail="invalid slug")
    paths = state.snapshot_paths()
    rows = user_view.deliveries_inline(conn, target_id=user_id, slug=slug, limit=50)
    seen = user_view.seen_post_ids(paths.state_dir, slug)
    return _partial("_user_deliveries.html", request,
                    rows=rows, slug=slug, user_id=user_id, seen=seen)


# --- /users 액션 (HTMX POST) --- #
@app.post("/users/{user_id}/poll-now-slug", response_class=HTMLResponse)
async def users_action_poll(request: Request,
                            user_id: str = Depends(require_user_id),
                            slugs: str = Form(...)):
    # 콤마 구분. dashboard 단에서 1차 검증, remote.py 가 2차.
    parts = [s.strip() for s in slugs.split(",") if s.strip()]
    if not parts or not all(state.safe_slug(s) for s in parts):
        raise HTTPException(status_code=400, detail="invalid slugs")
    res = await ctrl.users_poll_now_slug(",".join(parts))
    return _partial("_control_result.html", request, res=res, title=f"poll-now-slug(user={user_id})")


@app.post("/users/{user_id}/replay", response_class=HTMLResponse)
async def users_action_replay(request: Request,
                              user_id: str = Depends(require_user_id),  # noqa: ARG001 (audit log 용도)
                              slug: str = Form(...),
                              target_kind: str = Form(...),
                              target_id: str = Form(...),
                              post_id: Optional[str] = Form(None)):
    if not state.safe_slug(slug):
        raise HTTPException(status_code=400, detail="invalid slug")
    if target_kind not in ("dm", "channel"):
        raise HTTPException(status_code=400, detail="invalid target_kind")
    if not _USER_ID_RE.match(target_id or ""):
        raise HTTPException(status_code=400, detail="invalid target_id")
    pid = (post_id or "").strip() or None
    res = await ctrl.users_replay(slug, target_kind, target_id, pid)
    title = f"replay({slug},{target_kind}:{target_id}" + (f",post={pid})" if pid else ",bulk)")
    return _partial("_control_result.html", request, res=res, title=title)


@app.post("/users/{user_id}/notify-target", response_class=HTMLResponse)
async def users_action_notify_target(request: Request,
                                     user_id: str = Depends(require_user_id),  # noqa: ARG001
                                     slug: str = Form(...),
                                     target_kind: str = Form(...),
                                     target_id: str = Form(...)):
    if not state.safe_slug(slug):
        raise HTTPException(status_code=400, detail="invalid slug")
    if target_kind not in ("dm", "channel"):
        raise HTTPException(status_code=400, detail="invalid target_kind")
    if not _USER_ID_RE.match(target_id or ""):
        raise HTTPException(status_code=400, detail="invalid target_id")
    res = await ctrl.users_notify_target(slug, target_kind, target_id)
    return _partial("_control_result.html", request, res=res,
                    title=f"notify-target({slug},{target_kind}:{target_id})")


@app.post("/users/{user_id}/m1-solo", response_class=HTMLResponse)
async def users_action_m1_solo(request: Request,
                               user_id: str = Depends(require_user_id),  # noqa: ARG001
                               slug: str = Form(...),
                               target_kind: str = Form(...),
                               target_id: str = Form(...)):
    if not state.safe_slug(slug):
        raise HTTPException(status_code=400, detail="invalid slug")
    if target_kind not in ("dm", "channel"):
        raise HTTPException(status_code=400, detail="invalid target_kind")
    if not _USER_ID_RE.match(target_id or ""):
        raise HTTPException(status_code=400, detail="invalid target_id")
    res = await ctrl.users_m1_solo(slug, target_kind, target_id)
    return _partial("_control_result.html", request, res=res,
                    title=f"m1-solo({slug},{target_kind}:{target_id})")


_ANN_TITLE_MAX = 200
_ANN_MSG_MAX = 1900


@app.post("/users/announce", response_class=HTMLResponse)
async def users_action_announce(request: Request,
                                title: str = Form(...),
                                message: str = Form(...),
                                recipients_json: str = Form(...),
                                conn=Depends(get_conn)):
    """Scoped announce. recipients_json = JSON `[[kind,id],...]`.

    검증:
      - title / message 길이
      - recipients 가 list 이고 각 항목 [kind,id], kind ∈ {dm,channel}, id 가 snowflake
    """
    if conn is None:
        return _no_snapshot(request)
    title_s = (title or "").strip()
    msg_s = (message or "").strip()
    if not title_s or len(title_s) > _ANN_TITLE_MAX:
        raise HTTPException(status_code=400, detail="invalid title")
    if not msg_s or len(msg_s) > _ANN_MSG_MAX:
        raise HTTPException(status_code=400, detail="invalid message")
    try:
        recipients = json.loads(recipients_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid recipients JSON")
    if not isinstance(recipients, list) or not recipients:
        raise HTTPException(status_code=400, detail="recipients empty")
    cleaned: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in recipients:
        if not (isinstance(item, list) and len(item) == 2):
            raise HTTPException(status_code=400, detail="bad recipient shape")
        kind, rid = item
        if kind not in ("dm", "channel"):
            raise HTTPException(status_code=400, detail=f"bad kind: {kind!r}")
        if not isinstance(rid, str) or not _USER_ID_RE.match(rid):
            raise HTTPException(status_code=400, detail=f"bad id: {rid!r}")
        key = (kind, rid)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(key)
    res = await ctrl.users_announce(title_s, msg_s, sent_by="dashboard",
                                    recipients=cleaned)
    return _partial("_control_result.html", request, res=res,
                    title=f"announce(n={len(cleaned)})")


@app.get("/users/announce/resolve-slugs", response_class=HTMLResponse)
async def users_announce_resolve_slugs(request: Request,
                                       slugs: str = Query(...),
                                       conn=Depends(get_conn)):
    """폼 모달 안 'slug 들의 모든 구독자 추가' — slug csv → resolved recipients JSON.

    HTMX 가 GET 으로 호출, JSON 응답을 input value 에 prefill.
    """
    if conn is None:
        return HTMLResponse("[]", media_type="application/json")
    parts = [s.strip() for s in slugs.split(",") if s.strip()]
    if not parts or not all(state.safe_slug(s) for s in parts):
        return HTMLResponse("[]", media_type="application/json", status_code=400)
    seen: set[tuple[str, str]] = set()
    out: list[list[str]] = []
    for slug in parts:
        for r in db.subscriptions_for_slug(conn, slug):
            key = (r["target_kind"], r["target_id"])
            if key in seen:
                continue
            seen.add(key)
            out.append([r["target_kind"], r["target_id"]])
    return HTMLResponse(json.dumps(out), media_type="application/json")


# --------------------------------------------------------------------------- #
# Timings — workflow trace gantt
# --------------------------------------------------------------------------- #
from datetime import datetime as _dt


def _ts_str(t: float) -> str:
    try:
        return _dt.fromtimestamp(float(t)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return "—"


def _attrs_short(attrs: dict) -> str:
    if not attrs:
        return ""
    parts = []
    for k, v in attrs.items():
        s = str(v)
        if len(s) > 40:
            s = s[:37] + "…"
        parts.append(f"{k}={s}")
        if sum(len(p) for p in parts) > 140:
            break
    return "  ".join(parts)


@app.get("/timings", response_class=HTMLResponse)
async def timings_index(request: Request,
                        kind: Optional[str] = Query(None),
                        q: Optional[str] = Query(None),
                        failed: Optional[str] = Query(None),
                        idle: Optional[str] = Query(None),
                        limit: int = Query(100, ge=10, le=500)):
    ok, entries, err = await tracing_view.fetch_index_all()
    selected_kinds = {kind} if kind else None
    entries = tracing_view.filter_sort_entries(
        entries, kinds=selected_kinds, only_failed=bool(failed),
        include_idle=bool(idle), slug_q=q, limit=limit,
    )
    # 표시용 변환.
    rows = []
    for e in entries:
        rows.append({
            "trace_id": e.trace_id, "kind": e.kind, "attrs": e.attrs,
            "t_start_str": _ts_str(e.t_start_wall),
            "duration_ms": e.duration_ms, "n_spans": e.n_spans,
            "ok": e.ok, "ended": e.ended,
            "attrs_short": _attrs_short(e.attrs),
        })
    return _render("timings.html", request,
                   active="timings", entries=rows, ok=ok, err=err,
                   known_kinds=tracing_view.KNOWN_KINDS,
                   selected_kind=kind or "", q=q or "",
                   only_failed=bool(failed), include_idle=bool(idle),
                   limit=limit)


@app.get("/timings/{trace_id}", response_class=HTMLResponse)
async def timings_detail(request: Request, trace_id: str):
    # path-traversal 방어 — engine.tracing.valid_trace_id 와 일치.
    from engine.tracing import valid_trace_id as _vti
    if not _vti(trace_id):
        raise HTTPException(status_code=404, detail="invalid trace_id")
    detail = await tracing_view.load_trace_detail(trace_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="trace not found")
    gantt = tracing_view.build_gantt(detail)
    return _render("timings_detail.html", request,
                   active="timings", trace=detail, gantt=gantt,
                   start_str=_ts_str(detail.t_start_wall))


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #
@app.get("/reports", response_class=HTMLResponse)
async def reports_list(request: Request, status: str = "open",
                       count: int = Query(50, ge=1, le=500),
                       conn=Depends(get_conn)):
    if conn is None:
        return _no_snapshot(request)
    s = None if status == "all" else status
    rows = [dict(r) for r in db.list_reports(conn, status=s, limit=count)]
    bulk_prompt = prompts.report_triage_bulk(
        report_ids=[r["id"] for r in rows]) if rows and status == "open" else None
    return _render("reports.html", request,
                   rows=rows, filter_status=status, count=count,
                   bulk_prompt=bulk_prompt, active="reports")


@app.get("/reports/{report_id}", response_class=HTMLResponse)
async def report_detail(request: Request, report_id: int, conn=Depends(get_conn)):
    if conn is None:
        return _no_snapshot(request)
    paths = state.snapshot_paths()
    result = inspector.inspect(conn, paths, report_id=report_id)
    if result is None:
        return HTMLResponse(f"<p>신고 #{report_id} 없음.</p>", status_code=404)
    rp = result.report or {}
    p_single = prompts.report_triage_single(
        report_id=report_id,
        slug=result.slug,
        issue=rp.get("issue"),
        reporter=rp.get("username") or rp.get("user_id"),
    )
    return _render("report_detail.html", request,
                   result=result, report=rp, p_single=p_single, active="reports")


# --------------------------------------------------------------------------- #
# Feedback
# --------------------------------------------------------------------------- #
@app.get("/feedback", response_class=HTMLResponse)
async def feedback_list(request: Request, count: int = Query(50, ge=1, le=500),
                        conn=Depends(get_conn)):
    if conn is None:
        return _no_snapshot(request)
    rows = [dict(r) for r in db.list_feedback(conn, limit=count)]
    return _render("feedback.html", request, rows=rows, count=count, active="feedback")


# --------------------------------------------------------------------------- #
# Usage (LLM 호출 기록)
# --------------------------------------------------------------------------- #
_USAGE_RANGES = ("today", "7d", "30d", "all")


@app.get("/usage", response_class=HTMLResponse)
async def usage_page(request: Request,
                     range: str = Query("7d"),  # noqa: A002 (shadow built-in OK — FastAPI 파라미터)
                     call_site: Optional[str] = None,
                     limit: int = Query(100, ge=1, le=1000)):
    rng = range if range in _USAGE_RANGES else "7d"
    conn = usage_view.open_usage_conn(state.usage_db_path())
    if conn is None:
        return _render("usage.html", request, present=False, active="usage")
    try:
        since = usage_view.since_iso_for(rng)
        kpis = usage_view.usage_kpis(conn, since_iso=since, call_site=call_site)
        matrix = usage_view.usage_matrix(conn, since_iso=since)
        recent = usage_view.usage_recent(conn, since_iso=since, call_site=call_site, limit=limit)
        series = usage_view.usage_daily_series(conn, days=14)
        sites = usage_view.list_call_sites(conn)
    finally:
        conn.close()
    return _render("usage.html", request, present=True,
                   kpis=kpis, matrix=matrix, recent=recent, series=series,
                   call_sites=sites, range=rng, ranges=_USAGE_RANGES,
                   filter_call_site=call_site, limit=limit,
                   active="usage")


# --------------------------------------------------------------------------- #
# Control (5 섹션 — routing / runtime / env / timer / commands)
# --------------------------------------------------------------------------- #
@app.get("/control", response_class=HTMLResponse)
async def control_page(request: Request, load_remote: int = Query(0)):
    st = await ctrl.gather_state(load_remote=bool(load_remote))
    return _render("control.html", request, ctrl=st, load_remote=bool(load_remote), active="control")


@app.post("/control/save/routing", response_class=HTMLResponse)
async def control_save_routing(request: Request):
    form = await request.form()
    routing = {
        "config_generate":  form.get("config_generate", ""),
        "config_retry":     form.get("config_retry", ""),
        "notify_summarize": form.get("notify_summarize", ""),
        "notify_filter":    form.get("notify_filter", ""),
        "_default":         form.get("_default", ""),
    }
    res = await ctrl.save_routing(routing)
    return _partial("_control_result.html", request, res=res, title="routing")


@app.post("/control/save/runtime", response_class=HTMLResponse)
async def control_save_runtime(request: Request):
    form = await request.form()
    restart = bool(form.get("restart"))
    try:
        toml_text = ctrl.build_runtime_toml(dict(form))
    except ValueError as e:
        res = {"ok": False, "rc": -1, "output": str(e)}
        return _partial("_control_result.html", request, res=res, title="runtime")
    res = await ctrl.save_runtime(toml_text, restart=restart)
    return _partial("_control_result.html", request, res=res, title="runtime")


@app.post("/control/save/env", response_class=HTMLResponse)
async def control_save_env(request: Request, data: str = Form(...),
                           restart: Optional[str] = Form(None)):
    res = await ctrl.save_env(data, restart=bool(restart))
    return _partial("_control_result.html", request, res=res, title="env")


@app.post("/control/save/timer", response_class=HTMLResponse)
async def control_save_timer(request: Request, oncalendar: str = Form(...),
                             restart: Optional[str] = Form(None)):
    res = await ctrl.save_timer(oncalendar, restart=bool(restart))
    return _partial("_control_result.html", request, res=res, title="timer")


_REMOTE_ACTIONS = {
    "poll-now":      ("poll-now",),
    "restart-bot":   ("restart-bot",),
    "daemon-reload": ("daemon-reload",),
}
_REMOTE_LOG_UNITS = {"bot", "poll", "notify"}


@app.post("/control/cmd/{action}", response_class=HTMLResponse)
async def control_cmd(request: Request, action: str,
                      unit: Optional[str] = Form(None),
                      tail: int = Form(100)):
    if action in _REMOTE_ACTIONS:
        res = await ctrl.run_remote(*_REMOTE_ACTIONS[action])
    elif action == "status":
        u = unit if unit in {"bot", "poll", "notify", "poll-timer"} else "bot"
        res = await ctrl.run_remote("status", u)
        # systemctl status 는 one-shot 서비스가 inactive 면 rc=3 반환 — 마지막 run 이 성공해도.
        # 출력의 `Active:` 줄을 보고 의미 있는 ok/fail 로 재해석.
        res["ok"] = ctrl.interpret_systemctl_status(res["output"]) != "failed"
        res["status_state"] = ctrl.interpret_systemctl_status(res["output"])
    elif action == "logs":
        if unit not in _REMOTE_LOG_UNITS:
            raise HTTPException(status_code=400, detail="invalid unit")
        res = await ctrl.run_remote("logs", unit, "--tail", str(int(tail)))
    else:
        raise HTTPException(status_code=400, detail="unknown action")
    return _partial("_control_result.html", request, res=res, title=f"cmd:{action}")


# --------------------------------------------------------------------------- #
# Settings (read-only)
# --------------------------------------------------------------------------- #
@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    paths = state.snapshot_paths()
    info = {
        "snapshot_db": str(paths.db_path),
        "configs_dir": str(paths.configs_dir),
        "state_dir": str(paths.state_dir),
        "last_pull": state.last_pull_str(),
        "snapshot_present": state.snapshot_exists(),
        "n_configs": sum(1 for _ in paths.configs_dir.glob("*.json")) if paths.configs_dir.exists() else 0,
        "n_states": sum(1 for _ in paths.state_dir.glob("*.json")) if paths.state_dir.exists() else 0,
        "n_failed": len(state.failed_slugs()),
    }
    return _render("settings.html", request, info=info, active="settings")


# --------------------------------------------------------------------------- #
# Actions (HTMX)
# --------------------------------------------------------------------------- #
@app.post("/actions/pull", response_class=HTMLResponse)
async def actions_pull(request: Request):
    res = await act.run_pull()
    return _partial("_pull_result.html", request, res=res)


@app.post("/actions/fetch", response_class=HTMLResponse)
async def actions_fetch(request: Request, slug: str = Form(...),
                        n: int = Form(5)):
    if not state.safe_slug(slug):
        raise HTTPException(status_code=400, detail="invalid slug")
    res = await act.run_fetch(slug, n=n)
    return _partial("_fetch_result.html", request, res=res, slug=slug, n=n)


# --------------------------------------------------------------------------- #
@app.get("/healthz")
async def healthz():
    return {"ok": True, "snapshot": state.snapshot_exists()}
