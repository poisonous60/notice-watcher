"""FastAPI app + all routes.

Owner 1인용·localhost 한정·인증 0. 페이지 네비게이션은 일반 링크, HTMX 는 액션(Pull/Fetch) 과
부분 갱신용으로만 씀.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import html as _html

import jinja2
from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from bot import db, inspector
from dashboard import actions as act
from dashboard import bugs_view
from dashboard import candidates_view
from dashboard import cases_view
from dashboard import learned_view
from dashboard import vocab_deferred_view
from dashboard import clustering
from dashboard import prompts, state, triage_later
from dashboard import usage_view
from dashboard import user_view
from dashboard import control_actions as ctrl
from dashboard import history_view
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

# fail_taxonomy 카탈로그 → 템플릿 헬퍼 (filter dropdown / badge color 한 곳에서 derive).
from bot.fail_taxonomy import (  # noqa: E402
    fail_filter_options as _fail_filter_options,
    severity_for_kind as _severity_for_kind,
    label_for_kind as _label_for_kind,
)
templates.env.globals["fail_filter_options"] = _fail_filter_options
templates.env.globals["severity_for_kind"] = _severity_for_kind
templates.env.globals["label_for_kind"] = _label_for_kind

# --------------------------------------------------------------------------- #
# Page → required snapshot sources 매핑 (2026-05-20 page-scoped pull).
# 키 = URL path prefix. 값 = pull 해야 하는 source 이름 tuple.
# 빈 tuple = snapshot 미사용 페이지 (pull X — ssh 호출조차 안 함).
#
# 매핑 룰:
#   - 행동 기록 (job/report/feedback/delivery) 는 bot.sqlite3 에만 있음 → bot_db.
#   - 일부 페이지는 poll_state 부수 메타 사용 (broken counter, FAILED payload, seen_post_ids).
#   - /usage 만 usage_db. /learned 만 learned. configs 는 cfg_path.exists() 검사용 — bot_db 동반 페이지에 묶음.
#
# prefix 매칭은 *긴 prefix 우선* (e.g. /triage/failed 가 /triage 보다 먼저 매칭돼야 함).
# 아래 선언 순서와 무관하게 _sources_for_path 가 길이 desc 로 정렬해서 매칭 — 순서 footgun 제거.
# --------------------------------------------------------------------------- #
PAGE_SOURCES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # 0-source (snapshot 미사용 — control_audit/traces/cases.sqlite3 등 dev 로컬 또는 미pull)
    ("/control",     ()),
    ("/settings",    ()),
    ("/history",     ()),
    ("/timings",     ()),
    ("/cases",       ()),
    ("/vocab",       ()),
    # snapshot 의존 — 0-source 아님
    ("/candidates",  ("bot_db", "configs")),  # catalog yaml(로컬) × jobs 분포(bot_db) × config 존재(configs)
    ("/bugs",        ("poll_state",)),         # *.BUG.json (poll_state dir)
    ("/learned",     ("learned",)),
    # 단일 source
    ("/usage",        ("usage_db",)),
    ("/triage/failed", ("poll_state",)),  # *.FAILED.json 만 봄
    ("/clusters",    ("configs", "poll_state")),  # recognizer 승급 후보 — config 묶음 × url(poll_state)
    # bot_db 위주 + 일부 부수
    ("/jobs",        ("bot_db",)),
    ("/reports",     ("bot_db",)),
    ("/feedback",    ("bot_db",)),
    ("/subs",        ("bot_db", "poll_state", "configs")),
    ("/users",       ("bot_db", "poll_state")),
    ("/triage",      ("bot_db", "poll_state")),
    # 루트 (홈 트리아지)
    ("/",            ("bot_db", "poll_state")),
)


# 길이 desc 정렬 — 긴 prefix 가 먼저 매칭 (/triage/failed > /triage). 선언 순서 무관.
_PAGE_SOURCES_SORTED = tuple(sorted(PAGE_SOURCES, key=lambda kv: len(kv[0]), reverse=True))


def _sources_for_path(path: str) -> tuple[str, ...]:
    """path → 필요 source tuple. 가장 긴 매칭 prefix 적용. 매칭 없으면 ()."""
    for prefix, srcs in _PAGE_SOURCES_SORTED:
        if prefix == "/":
            if path == "/":
                return srcs
            continue
        if path == prefix or path.startswith(prefix + "/"):
            return srcs
    return ()


@asynccontextmanager
async def _lifespan(app):
    """Startup: cold cache 채우기 — 전체 source 1회 pull. 실패해도 dashboard 는 뜸 (snapshot 없는 안내 페이지)."""
    try:
        await act.ensure_fresh_snapshot(force=True)
    except Exception:  # noqa: BLE001
        pass
    yield


app = FastAPI(title="notice-watcher dashboard", docs_url=None, redoc_url=None,
              lifespan=_lifespan)
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")


# --------------------------------------------------------------------------- #
# Preflight pull middleware — 페이지별 needed source 만 fresh 보장.
# 2026-05-20: 페이지 전체 pull → page-scoped per-source pull 로 변경. 무한 로딩 제거.
# - 대부분 nav: ssh marker fetch 1회 (~0.5s), source 변경 X → pull 안 함
# - source 변경됐을 때만 그 source 만 pull
# - source 0 페이지 (/control 등): ssh 호출조차 안 함
# --------------------------------------------------------------------------- #
@app.middleware("http")
async def _preflight_pull(request: Request, call_next):
    """페이지 렌더 전에 필요한 source 만 fresh 보장.

    범위: 일반 페이지 GET. /static, /actions, /healthz, /favicon.ico 와 HTMX sub-request 는 skip.
    실패 시 stale snapshot 으로 fallback + 토픽바에 경고 (`pull_result.ok=False`).
    """
    path = request.url.path
    skip_prefix = ("/static", "/actions", "/healthz", "/favicon")
    is_page = (
        request.method == "GET"
        and not path.startswith(skip_prefix)
        and request.headers.get("hx-request") != "true"
    )
    if is_page:
        needed = _sources_for_path(path)
        try:
            request.state.pull_result = await act.ensure_sources_fresh(needed)
        except Exception as e:  # noqa: BLE001
            request.state.pull_result = {
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "pulled": [], "skipped": [], "failed": list(needed), "marker_ok": False,
            }
    return await call_next(request)


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
        # preflight middleware 가 채움. 페이지 GET 이 아닌 경로(HTMX partial 등) 에선 None.
        "pull_result": getattr(request.state, "pull_result", None),
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
    later = triage_later.load()
    active_failed = [s for s in summary["failed_slugs"] if s not in later]
    later_failed = [s for s in summary["failed_slugs"] if s in later]
    quick_prompts = {
        "report_triage_bulk": prompts.report_triage_bulk(
            report_ids=[r["id"] for r in db.list_reports(conn, status="open", limit=200)]
        ) if summary["open_reports"] > 0 else None,
        "hand_config_triage": prompts.hand_config_triage_queue(
            failed_slugs=active_failed
        ) if active_failed else None,
    }
    return _render("triage.html", request,
                   summary=summary, recent=rows, quick=quick_prompts,
                   active_failed_count=len(active_failed),
                   later_failed_count=len(later_failed),
                   active="triage")


@app.get("/triage/failed", response_class=HTMLResponse)
async def triage_failed_page(request: Request):
    """자동등록 실패(FAILED.json) 큐 한눈 — snapshot 의 `*.FAILED.json` 들을 한 줄씩 표로.

    한 행만; last_feedback / last_config 원문은 `/subs/<slug>` 상세에서 본다.
    '나중에' 토글된 slug 는 별도 섹션 (dashboard view 만 분리 — N100 영향 X).
    """
    later = triage_later.load()
    active: list[dict] = []
    later_items: list[dict] = []
    for slug in state.failed_slugs():
        d = state.failed_payload(slug) or {}
        lines = [ln.strip() for ln in (d.get("last_feedback") or "").splitlines() if ln.strip()]
        first_fail = next((ln for ln in lines if "[FAIL]" in ln), lines[0] if lines else "")
        row = {
            "slug": slug,
            "url": d.get("url") or "",
            "failed_at": (d.get("failed_at") or "")[:19],
            "reason": d.get("reason") or "",
            "first_fail": first_fail,
        }
        (later_items if slug in later else active).append(row)
    active.sort(key=lambda r: r["failed_at"], reverse=True)
    later_items.sort(key=lambda r: r["failed_at"], reverse=True)
    return _render("triage_failed.html", request,
                   items=active, later_items=later_items, active="triage")


@app.post("/triage/failed/later", response_class=HTMLResponse)
async def triage_failed_later(request: Request):
    """체크박스 일괄 토글. action=add → 나중에 섹션으로, action=remove → 활성 복귀.

    Form fields:
      - action: "add" | "remove"
      - slugs: 반복 (체크된 행마다 한 값)
    """
    form = await request.form()
    action = (form.get("action") or "").strip()
    if action not in ("add", "remove"):
        raise HTTPException(status_code=400, detail="invalid action")
    slugs = [s for s in form.getlist("slugs") if isinstance(s, str)]
    if not all(state.safe_slug(s) for s in slugs):
        raise HTTPException(status_code=400, detail="invalid slug")
    if slugs:
        if action == "add":
            triage_later.add_many(slugs)
        else:
            triage_later.remove_many(slugs)
    return RedirectResponse(url="/triage/failed", status_code=303)


@app.get("/clusters", response_class=HTMLResponse)
async def clusters_page(request: Request):
    """recognizer 승급 후보 — 자동생성 config 중 같은 platform(param 만 다름) 묶음.

    snapshot 의 configs.snapshot/ + poll_state/ 를 소스로 clustering.compute_clusters 호출.
    [A] same-host (검색어/board 만 다름) / [B] cross-host CMS. 이미 recognize() 되는 건 제외(봉합).
    각 cluster 마다 recognizer-extension 스킬 트리거 프롬프트 첨부 (복사 → 붙여넣기).
    """
    paths = state.snapshot_paths()
    res = clustering.compute_clusters(paths.configs_dir, paths.state_dir)
    for c in res["same_host"] + res["cross_host"]:
        c["prompt"] = prompts.recognizer_extension_cluster(
            host_or_template=c["key"], members=c["member_pairs"])
    return _render("clusters.html", request, res=res, active="clusters")


# --------------------------------------------------------------------------- #
# Jobs
# --------------------------------------------------------------------------- #
@app.get("/jobs", response_class=HTMLResponse)
async def jobs_list(request: Request, count: int = Query(50, ge=1, le=200),
                    page: int = Query(1, ge=1),
                    status: Optional[str] = None, q: Optional[str] = None,
                    conn=Depends(get_conn)):
    if conn is None:
        return _no_snapshot(request)
    offset = (page - 1) * count
    from bot.fail_taxonomy import BASE_STATUS_VALUES
    # base status (pending/running/done/failed) → SQL pushdown. fail_kind (gen_fail/policy_reject/gate_reject/bug)
    # → SQL pushdown 'failed' + Python sub-filter (page 폭 안 행에서 fail_kind 매칭 — 윈도우 밖 누락 가능,
    # 다음 페이지 가면 그 다음 50건 failed 안에서 다시 매칭).
    sql_status: Optional[str]
    if status and status in BASE_STATUS_VALUES:
        sql_status = status
    elif status:
        sql_status = "failed"
    else:
        sql_status = None
    rows = inspector.recent_jobs(conn, limit=count + 1, offset=offset, status=sql_status)
    has_next = len(rows) > count
    rows = rows[:count]
    if status and status not in BASE_STATUS_VALUES:
        rows = [r for r in rows if r.get("fail_kind") == status]
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
                   rows=rows, count=count, filter_status=status, q=q,
                   page=page, has_next=has_next, active="jobs")


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: int, conn=Depends(get_conn)):
    if conn is None:
        return _no_snapshot(request)
    paths = state.snapshot_paths()
    result = inspector.inspect(conn, paths, job_id=job_id)
    if result is None:
        return HTMLResponse("<p>잡 없음.</p>", status_code=404)
    j = result.latest_job or {}
    from bot.fail_taxonomy import classify_fail
    j_kind, j_sub, j_reason = classify_fail(j.get("status"), j.get("result_rc"), j.get("result_tail"))
    # hand-config 프롬프트에 넘기는 fail_reason — 풀 라인 (subkind 가 있으면 subkind 도 prefix 로).
    if j_kind in ("done", "pending", "running"):
        fail_reason = None
    else:
        fail_reason = j_reason or f"status={j.get('status')} rc={j.get('result_rc')}"
        if j_sub:
            fail_reason = f"[{j_kind}:{j_sub}] {fail_reason}"
    p_handconfig = prompts.hand_config_for_url(
        url=j.get("url") or "",
        slug=result.slug,
        fail_reason=fail_reason,
        job_id=job_id,
    )
    return _render("job_detail.html", request,
                   result=result, job=j, p_handconfig=p_handconfig,
                   fail_kind=j_kind, fail_subkind=j_sub, fail_reason_short=j_reason,
                   active="jobs")


# --------------------------------------------------------------------------- #
# Subs (slug 기준)
# --------------------------------------------------------------------------- #
@app.get("/subs", response_class=HTMLResponse)
async def subs_list(request: Request, q: Optional[str] = None,
                    include_lurking: int = 0, broken_only: int = 0,
                    conn=Depends(get_conn)):
    if conn is None:
        return _no_snapshot(request)
    paths = state.snapshot_paths()
    # 자동등록 *실패* 만 한 slug 는 subscriptions 테이블에 행이 없다 — DB-only 목록이면 누락 →
    # /subs 가 활성+FAILED 둘 다 보이도록 합집합. (FAILED 큐 상세는 /triage/failed)
    # include_lurking=1 이면 구독자 0 + state 파일만 있는 slug (lurking) 도 포함.
    base = set(state.unique_slugs(conn)) | set(state.failed_slugs())
    if include_lurking:
        base |= set(state.state_file_slugs())
    slugs = sorted(base)
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
        sample_url = subs[0]["url"] if subs else None
        if sample_url is None and failed_marker.exists():
            fp = state.failed_payload(s) or {}
            sample_url = fp.get("url")
        rows.append({
            "slug": s,
            "n_subs": len(subs),
            "has_config": cfg_path.exists(),
            "has_state": st_path.exists(),
            "failed": failed_marker.exists(),
            "broken": broken,
            "sample_url": sample_url,
            "user_ids": user_ids,
        })
    rows.sort(key=lambda r: (-r["broken"], not r["failed"], r["slug"]))
    if broken_only:
        rows = [r for r in rows if r["broken"] > 0]
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
    return _render("subs.html", request, rows=rows, q=q,
                   include_lurking=bool(include_lurking),
                   broken_only=bool(broken_only),
                   active="subs")


@app.get("/subs/{slug}", response_class=HTMLResponse)
async def sub_detail(request: Request, slug: str = Depends(require_slug),
                     from_: Optional[str] = Query(None, alias="from"),
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
    # 뒤로가기 — 어디서 왔는지에 따라. 기본은 /subs.
    back = {"triage": ("/triage/failed", "FAILED 큐")}.get(from_ or "", ("/subs", "Subs"))
    return _render("sub_detail.html", request,
                   result=result, slug=slug, failed=failed_payload,
                   p_redo=p_redo, p_diag=p_diag,
                   back_href=back[0], back_label=back[1], active="subs")


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


@app.get("/history", response_class=HTMLResponse)
async def history_index(request: Request,
                        category: Optional[str] = Query(None),
                        q: Optional[str] = Query(None),
                        failed: Optional[str] = Query(None),
                        limit: int = Query(200, ge=10, le=2000),
                        page: int = Query(1, ge=1)):
    """dashboard 액션 audit (output/control_audit.jsonl) tail + 필터 표."""
    cat = (category or "").strip()
    if cat and cat not in history_view.CATEGORIES:
        cat = ""
    offset = (page - 1) * limit
    rows, total, has_next = history_view.load_rows(
        limit=limit, offset=offset, category=cat,
        only_failed=bool(failed), q=(q or "").strip(),
    )
    return _render("history.html", request,
                   active="history", rows=rows, total=total,
                   categories=history_view.CATEGORIES,
                   selected_category=cat, q=q or "",
                   only_failed=bool(failed), limit=limit,
                   page=page, has_next=has_next,
                   max_tail=history_view.MAX_TAIL_LINES)


@app.get("/timings", response_class=HTMLResponse)
async def timings_index(request: Request,
                        kind: Optional[str] = Query(None),
                        q: Optional[str] = Query(None),
                        failed: Optional[str] = Query(None),
                        idle: Optional[str] = Query(None),
                        source: str = Query("snapshot"),
                        limit: int = Query(100, ge=10, le=500),
                        page: int = Query(1, ge=1)):
    src = source if source in tracing_view.TRACE_SOURCES else "snapshot"
    ok, entries, err = await tracing_view.fetch_index_all(source=src)
    selected_kinds = {kind} if kind else None
    offset = (page - 1) * limit
    entries, has_next = tracing_view.filter_sort_entries(
        entries, kinds=selected_kinds, only_failed=bool(failed),
        include_idle=bool(idle), slug_q=q, limit=limit, offset=offset,
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
                   source=src, sources=tracing_view.TRACE_SOURCES,
                   limit=limit, page=page, has_next=has_next)


@app.get("/timings/{trace_id}", response_class=HTMLResponse)
async def timings_detail(request: Request, trace_id: str,
                         source: str = Query("snapshot")):
    # path-traversal 방어 — engine.tracing.valid_trace_id 와 일치.
    from engine.tracing import valid_trace_id as _vti
    if not _vti(trace_id):
        raise HTTPException(status_code=404, detail="invalid trace_id")
    src = source if source in tracing_view.TRACE_SOURCES else "snapshot"
    detail = await tracing_view.load_trace_detail(trace_id, source=src)
    if detail is None:
        raise HTTPException(status_code=404, detail="trace not found")
    gantt = tracing_view.build_gantt(detail)
    return _render("timings_detail.html", request,
                   active="timings", trace=detail, gantt=gantt,
                   source=src, sources=tracing_view.TRACE_SOURCES,
                   start_str=_ts_str(detail.t_start_wall))


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #
@app.get("/reports", response_class=HTMLResponse)
async def reports_list(request: Request, status: str = "open",
                       count: int = Query(50, ge=1, le=500),
                       page: int = Query(1, ge=1),
                       conn=Depends(get_conn)):
    if conn is None:
        return _no_snapshot(request)
    s = None if status == "all" else status
    offset = (page - 1) * count
    raw = db.list_reports(conn, status=s, limit=count + 1, offset=offset)
    has_next = len(raw) > count
    rows = [dict(r) for r in raw[:count]]
    bulk_prompt = prompts.report_triage_bulk(
        report_ids=[r["id"] for r in rows]) if rows and status == "open" else None
    return _render("reports.html", request,
                   rows=rows, filter_status=status, count=count,
                   bulk_prompt=bulk_prompt,
                   page=page, has_next=has_next, active="reports")


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
                        page: int = Query(1, ge=1),
                        conn=Depends(get_conn)):
    if conn is None:
        return _no_snapshot(request)
    offset = (page - 1) * count
    raw = db.list_feedback(conn, limit=count + 1, offset=offset)
    has_next = len(raw) > count
    rows = [dict(r) for r in raw[:count]]
    return _render("feedback.html", request, rows=rows, count=count,
                   page=page, has_next=has_next, active="feedback")


# --------------------------------------------------------------------------- #
# Usage (LLM 호출 기록)
# --------------------------------------------------------------------------- #
_USAGE_RANGES = ("today", "7d", "30d", "all")


_USAGE_SOURCES = ("snapshot", "local")


@app.get("/usage", response_class=HTMLResponse)
async def usage_page(request: Request,
                     range: str = Query("7d"),  # noqa: A002 (shadow built-in OK — FastAPI 파라미터)
                     source: str = Query("snapshot"),
                     call_site: Optional[str] = None,
                     limit: int = Query(100, ge=1, le=1000),
                     page: int = Query(1, ge=1)):
    rng = range if range in _USAGE_RANGES else "7d"
    src = source if source in _USAGE_SOURCES else "snapshot"
    conn = usage_view.open_usage_conn(state.usage_db_path_for(src))
    if conn is None:
        return _render("usage.html", request, present=False, source=src,
                       sources=_USAGE_SOURCES, active="usage")
    try:
        since = usage_view.since_iso_for(rng)
        kpis = usage_view.usage_kpis(conn, since_iso=since, call_site=call_site)
        matrix = usage_view.usage_matrix(conn, since_iso=since)
        offset = (page - 1) * limit
        recent_raw = usage_view.usage_recent(
            conn, since_iso=since, call_site=call_site,
            limit=limit + 1, offset=offset)
        has_next = len(recent_raw) > limit
        recent = recent_raw[:limit]
        series = usage_view.usage_daily_series(conn, days=14)
        sites = usage_view.list_call_sites(conn)
    finally:
        conn.close()
    return _render("usage.html", request, present=True,
                   kpis=kpis, matrix=matrix, recent=recent, series=series,
                   call_sites=sites, range=rng, ranges=_USAGE_RANGES,
                   source=src, sources=_USAGE_SOURCES,
                   filter_call_site=call_site, limit=limit,
                   page=page, has_next=has_next,
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
    routing = ctrl.build_routing_form(dict(form))
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
# 자동 Pull 라우트는 사라짐 — middleware `_preflight_pull` 가 페이지 GET 전에 ensure_fresh_snapshot
# 으로 처리. 사용자가 force refresh 원하면 단순히 페이지를 다시 GET 하거나 TTL 만료 기다리면 됨.


@app.post("/actions/fetch", response_class=HTMLResponse)
async def actions_fetch(request: Request, slug: str = Form(...),
                        n: int = Form(5)):
    if not state.safe_slug(slug):
        raise HTTPException(status_code=400, detail="invalid slug")
    res = await act.run_fetch(slug, n=n)
    return _partial("_fetch_result.html", request, res=res, slug=slug, n=n)


# --------------------------------------------------------------------------- #
# Cases — skill 실행 audit (`docs/case_runs DB 계획.md`). dev box only.
# --------------------------------------------------------------------------- #
cases_view.register(app, templates, _render)
candidates_view.register(app, templates, _render)
learned_view.register(app, templates, _render)
bugs_view.register(app, templates, _render)
vocab_deferred_view.register(app, templates, _render)


# --------------------------------------------------------------------------- #
@app.get("/healthz")
async def healthz():
    return {"ok": True, "snapshot": state.snapshot_exists()}
