"""`/candidates` 라우트 (rev4) — catalog × N100 snapshot jobs 분포.

`configs/candidates/catalog.yaml` (schema 2: name+url) ↔ snapshot `bot.sqlite3` jobs
(LEFT JOIN on url) + `configs.snapshot/<slug>.json` config 존재 여부 → status ×
fail_kind/fail_subkind 분포. dev box 전용.

설계: `docs/사이트 카탈로그 자동 등록 파이프라인 계획.md` §6.
fail_kind/subkind 분류는 `bot.fail_taxonomy.classify_fail` 재사용 — `/jobs` 와 동일 어휘.

라우트:
  GET  /candidates                   — KPI(status × subkind) + 표
  POST /candidates/add               — name+url entry 추가
  POST /candidates/remove            — url entry 제거 (catalog.yaml 영구 변경)
  POST /candidates/batch-run         — N100 batch-register kick (subprocess remote.py)
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from bot import fail_taxonomy
from dashboard import state

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "configs" / "candidates" / "catalog.yaml"
CONFIGS_SNAPSHOT = ROOT / "configs.snapshot"
REMOTE_PY = ROOT / "scripts" / "remote.py"

# 표시 status 어휘 — fail_taxonomy kind 위에 'registered' / 'untried' 만 추가.
STATUS_DISPLAY: dict[str, tuple[str, str]] = {
    "registered":    ("✅", "등록됨"),
    "untried":       ("·",  "미시도"),
    "pending":       ("⏳", "큐 대기"),
    "running":       ("🔁", "처리중"),
    "done":          ("✅", "완료 (config 부재 race)"),
    "gen_fail":      ("❌", "자동등록 실패"),
    "policy_reject": ("🚫", "정책 거부"),
    "gate_reject":   ("🚫", "게이트 거부"),
    "bug":           ("🐞", "BUG"),
    "unknown":       ("⚠",  "분류 미스"),
}
STATUS_ORDER = [
    "untried", "pending", "running", "gen_fail", "policy_reject",
    "gate_reject", "bug", "unknown", "done", "registered",
]


# Header — round-trip 시 코멘트 소실되므로 매 write 마다 재박음.
_CATALOG_HEADER = """# 사이트 카탈로그 — `scripts/register_batch.py` 입력 (rev4 schema 2).
# (헤더는 dashboard add/remove 시 자동 재박음 — entry 안 inline 코멘트는 round-trip 시 소실.)
#
# 스키마: docs/사이트 카탈로그 자동 등록 파이프라인 계획.md §3.
# 필드: name (사람 읽는 라벨, 1~200자) + url (http(s) 게시판 목록 URL, ≤1000자).

"""


# --------------------------------------------------------------------------- #
# Catalog I/O
# --------------------------------------------------------------------------- #
def _load_catalog_doc() -> Optional[dict]:
    if not CATALOG_PATH.exists():
        return None
    try:
        import yaml
    except ImportError:
        return None
    try:
        doc = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return None
    if not isinstance(doc, dict):
        return None
    return doc


def _load_entries() -> list[dict]:
    doc = _load_catalog_doc()
    if doc is None:
        return []
    if doc.get("schema") != 2:
        return []
    entries = doc.get("entries") or []
    out: list[dict] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        name = e.get("name")
        url = e.get("url")
        if not isinstance(name, str) or not isinstance(url, str):
            continue
        out.append({"name": name, "url": url})
    return out


def _save_catalog_doc(doc: dict) -> None:
    try:
        import yaml
    except ImportError as e:
        raise RuntimeError("PyYAML 필요") from e
    payload = {
        "version": doc.get("version", 1),
        "schema": 2,
        "entries": doc.get("entries") or [],
    }
    yaml_text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False,
                                default_flow_style=False, width=200)
    full_text = _CATALOG_HEADER + yaml_text
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".catalog_", suffix=".yaml",
                                dir=str(CATALOG_PATH.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(full_text)
        os.replace(tmp, CATALOG_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# --------------------------------------------------------------------------- #
# Status classification
# --------------------------------------------------------------------------- #
def _url_to_slug(url: str) -> str:
    from probe.paths import url_to_slug
    return url_to_slug(url)


def _classify(slug: str, job_row: Optional[dict]) -> dict:
    """slug + 최신 jobs row → {status, subkind, last_ts, rc, reason, job_id, via}.

    config 존재면 'registered' override (worker 가 만든 결과물). 없으면 fail_taxonomy
    분류 — done(race) / gen_fail / policy_reject / gate_reject / bug / unknown.
    job row 없으면 'untried'.
    """
    config_exists = (CONFIGS_SNAPSHOT / f"{slug}.json").exists()
    if config_exists:
        return {
            "status": "registered", "subkind": "ok",
            "last_ts": ((job_row or {}).get("finished_at") or (job_row or {}).get("created_at") or "")[:19],
            "rc": (job_row or {}).get("result_rc") or 0,
            "reason": "",
            "job_id": (job_row or {}).get("id"),
            "via": (job_row or {}).get("via") or "",
        }
    if job_row is None:
        return {"status": "untried", "subkind": "—", "last_ts": "",
                "rc": None, "reason": "", "job_id": None, "via": ""}
    kind, subkind, reason = fail_taxonomy.classify_fail(
        job_row.get("status"), job_row.get("result_rc"), job_row.get("result_tail"),
    )
    return {
        "status": kind,
        "subkind": subkind or "—",
        "last_ts": (job_row.get("finished_at") or job_row.get("created_at") or "")[:19],
        "rc": job_row.get("result_rc"),
        "reason": reason or "",
        "job_id": job_row.get("id"),
        "via": job_row.get("via") or "",
    }


# --------------------------------------------------------------------------- #
# Snapshot jobs — most-recent register job per url.
# --------------------------------------------------------------------------- #
def _latest_jobs_by_url(conn: sqlite3.Connection) -> dict[str, dict]:
    out: dict[str, dict] = {}
    try:
        rows = conn.execute(
            """SELECT j.* FROM jobs j
               INNER JOIN (
                   SELECT url, MAX(id) AS max_id FROM jobs
                   WHERE kind='register' GROUP BY url
               ) m ON j.url = m.url AND j.id = m.max_id"""
        ).fetchall()
    except sqlite3.Error:
        return out
    for r in rows:
        out[r["url"]] = dict(r)
    return out


# --------------------------------------------------------------------------- #
# Row build / KPI / distribution
# --------------------------------------------------------------------------- #
def _build_rows(entries: list[dict], jobs_by_url: dict[str, dict]) -> list[dict]:
    out: list[dict] = []
    for e in entries:
        name = e["name"]
        url = e["url"]
        slug = _url_to_slug(url)
        cls = _classify(slug, jobs_by_url.get(url))
        emoji, label = STATUS_DISPLAY.get(cls["status"], ("?", cls["status"]))
        out.append({
            "name": name, "url": url, "slug": slug,
            "status": cls["status"],
            "status_emoji": emoji, "status_label": label,
            "subkind": cls["subkind"],
            "last_ts": cls["last_ts"],
            "rc": cls["rc"],
            "reason": cls["reason"],
            "via": cls["via"],
            "job_id": cls["job_id"],
        })
    return out


def _kpis(rows: list[dict]) -> dict[str, int]:
    out = {s: 0 for s in STATUS_ORDER}
    out["total"] = len(rows)
    for r in rows:
        s = r["status"]
        if s in out:
            out[s] += 1
    return out


def _distribution(rows: list[dict]) -> list[dict]:
    """status × subkind 카운트. fail/queue 계열만 (registered/untried 제외)."""
    buckets: dict[tuple[str, str], int] = {}
    for r in rows:
        if r["status"] in ("registered", "untried"):
            continue
        key = (r["status"], r["subkind"])
        buckets[key] = buckets.get(key, 0) + 1
    out = []
    for (st, sk), n in sorted(buckets.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1])):
        emoji, label = STATUS_DISPLAY.get(st, ("?", st))
        out.append({"status": st, "status_emoji": emoji, "status_label": label,
                    "subkind": sk, "count": n})
    return out


# --------------------------------------------------------------------------- #
# Filtering
# --------------------------------------------------------------------------- #
def _filter_rows(rows: list[dict], *, status, subkind, q) -> list[dict]:
    out = rows
    if status:
        statuses = {x.strip() for x in status.split(",") if x.strip()}
        out = [r for r in out if r["status"] in statuses]
    if subkind:
        sks = {x.strip() for x in subkind.split(",") if x.strip()}
        out = [r for r in out if r["subkind"] in sks]
    if q:
        ql = q.strip().lower()
        out = [r for r in out
               if ql in (r["name"] or "").lower()
               or ql in (r["url"] or "").lower()
               or ql in (r["slug"] or "").lower()]
    return out


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #
def register(app, templates, _render):  # noqa: ARG001
    @app.get("/candidates", response_class=HTMLResponse)
    async def candidates_page(
        request: Request,
        status: Optional[str] = Query(None),
        subkind: Optional[str] = Query(None),
        q: Optional[str] = Query(None),
    ):
        entries = _load_entries()
        warning: Optional[str] = None
        if not entries:
            if CATALOG_PATH.exists():
                warning = (
                    f"카탈로그 ({CATALOG_PATH.relative_to(ROOT)}) 가 비었거나 schema≠2. "
                    "`docs/사이트 카탈로그 자동 등록 파이프라인 계획.md` §3 참고."
                )
            else:
                warning = f"카탈로그 파일 없음: {CATALOG_PATH.relative_to(ROOT)}"

        jobs_by_url: dict[str, dict] = {}
        jobs_db_error: Optional[str] = None
        conn = state.open_conn()
        if conn is not None:
            try:
                jobs_by_url = _latest_jobs_by_url(conn)
            except sqlite3.Error as e:
                jobs_db_error = f"sqlite 오류: {type(e).__name__}: {e}"
            finally:
                conn.close()

        all_rows = _build_rows(entries, jobs_by_url)
        rows = _filter_rows(all_rows, status=status, subkind=subkind, q=q)
        rows.sort(key=lambda r: (STATUS_ORDER.index(r["status"])
                                  if r["status"] in STATUS_ORDER else 99,
                                  r["name"] or ""))
        kpis = _kpis(all_rows)
        distribution = _distribution(all_rows)
        all_statuses = sorted({r["status"] for r in all_rows})
        all_subkinds = sorted({r["subkind"] for r in all_rows if r["subkind"] not in ("—", "ok")})
        return _render(
            "candidates.html", request,
            rows=rows, kpis=kpis, distribution=distribution,
            catalog_warning=warning, jobs_db_error=jobs_db_error,
            total_filtered=len(rows), total_all=len(all_rows),
            facets={"statuses": all_statuses, "subkinds": all_subkinds},
            cur={"status": status or "", "subkind": subkind or "", "q": q or ""},
            status_display=STATUS_DISPLAY,
            status_order=STATUS_ORDER,
            catalog_path=str(CATALOG_PATH.relative_to(ROOT)),
            snapshot_ts=state.last_pull_str(),
            active="candidates",
        )

    @app.post("/candidates/remove", response_class=HTMLResponse)
    async def candidates_remove(url: str = Form(...)):
        u = (url or "").strip()
        if not u:
            raise HTTPException(status_code=400, detail="url 비어있음")
        doc = _load_catalog_doc()
        if doc is None:
            raise HTTPException(status_code=500, detail="catalog 로드 실패")
        entries = doc.get("entries") or []
        before = len(entries)
        doc["entries"] = [e for e in entries
                          if not (isinstance(e, dict) and e.get("url") == u)]
        if len(doc["entries"]) == before:
            raise HTTPException(status_code=404, detail=f"url 못 찾음: {u}")
        try:
            _save_catalog_doc(doc)
        except (OSError, RuntimeError) as e:
            raise HTTPException(status_code=500, detail=f"yaml 저장 실패: {e}")
        return RedirectResponse(url="/candidates", status_code=303)

    @app.post("/candidates/add", response_class=HTMLResponse)
    async def candidates_add(name: str = Form(...), url: str = Form(...)):
        nm = (name or "").strip()
        u = (url or "").strip()
        if not nm or len(nm) > 200:
            raise HTTPException(status_code=400, detail="invalid name (1~200자)")
        if not (u.startswith("http://") or u.startswith("https://")) or len(u) > 1000:
            raise HTTPException(status_code=400, detail="invalid url (http(s) 만, ≤1000자)")
        doc = _load_catalog_doc()
        if doc is None:
            raise HTTPException(status_code=500, detail="catalog 로드 실패")
        if doc.get("schema") != 2:
            raise HTTPException(status_code=500, detail="catalog schema≠2 — 마이그 먼저")
        entries = doc.get("entries") or []
        if any(isinstance(e, dict) and e.get("url") == u for e in entries):
            raise HTTPException(status_code=409, detail=f"url 중복: {u}")
        doc["entries"] = entries + [{"name": nm, "url": u}]
        try:
            _save_catalog_doc(doc)
        except (OSError, RuntimeError) as e:
            raise HTTPException(status_code=500, detail=f"yaml 저장 실패: {e}")
        return RedirectResponse(url="/candidates", status_code=303)

    @app.post("/candidates/batch-run", response_class=HTMLResponse)
    async def candidates_batch_run(force: str = Form("")):
        """`▶ batch run` 버튼 → subprocess `scripts/remote.py batch-register`.

        force=on (체크박스) 이면 `--force`. ssh stdout 캡처해 결과 페이지로 표시.
        """
        cmd = [sys.executable, str(REMOTE_PY), "batch-register"]
        force_on = force in ("on", "1", "true", "yes")
        if force_on:
            cmd.append("--force")
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, errors="replace",
                cwd=str(ROOT), timeout=600,
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="remote batch-register 600초 timeout")
        out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
        rc = proc.returncode
        html = (
            "<!doctype html><html><body>"
            "<article style='margin:1rem;font-family:system-ui,sans-serif'>"
            f"<h3>batch-register rc={rc}{' (force)' if force_on else ''}</h3>"
            f"<pre style='white-space:pre-wrap;max-height:60vh;overflow:auto;background:#f6f6f6;padding:0.5rem;border-radius:4px'>{_html_escape(out)}</pre>"
            "<p><a href='/candidates' role='button'>← 분포로 돌아가기</a></p>"
            "</article></body></html>"
        )
        return HTMLResponse(html, status_code=200 if rc == 0 else 500)


def _html_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
              .replace('"', "&quot;").replace("'", "&#39;"))
