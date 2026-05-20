"""`/candidates` 라우트 (rev6) — multi-file catalog × N100 snapshot jobs 분포.

rev6 변경: catalog yaml 위치 `configs/candidates/` → `output/candidates/`. git-ignored.
dashboard 가 dev box 의 copy 직접 편집. N100 은 `scripts/remote.py batch-register` 호출 시점에 동기.

`output/candidates/<name>.yaml` (schema 2: name+url) 각 파일 ↔ snapshot `bot.sqlite3`
jobs (LEFT JOIN on url) + `configs.snapshot/<slug>.json` config 존재 여부 → status ×
fail_kind/fail_subkind 분포. dev box 전용.

설계: `docs/사이트 카탈로그 자동 등록 파이프라인 계획.md` rev5 §8.

라우트:
  GET  /candidates                       — 카탈로그 목록 + 전체 KPI + "+ 새 catalog" 폼.
  GET  /candidates/<name>                — 특정 catalog 의 KPI + 분포 + entry 표 + bulk paste.
  POST /candidates/<name>/add-bulk       — bulk URL paste → 그 catalog 에 append.
  POST /candidates/<name>/remove         — url entry 제거.
  POST /candidates/new                   — 새 catalog 파일 생성 + bulk URLs 박음.

batch run 트리거 X (rev5 정책 — Claude/CLI 가 트리거).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sqlite3
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from bot import fail_taxonomy
from dashboard import prompts, state

ROOT = Path(__file__).resolve().parent.parent
CATALOG_DIR = ROOT / "output" / "candidates"  # rev6: git-ignored 데이터. dashboard 가 dev box copy 직접 편집.
                                                # N100 동기는 `scripts/remote.py batch-register` atomic scp 가 함.
CONFIGS_SNAPSHOT = ROOT / "configs.snapshot"

CATALOG_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
# URL extraction regex — bulk paste 에서 사용. trailing punct 제거는 후처리.
URL_EXTRACT_RE = re.compile(r"https?://[^\s<>\"'`\\]+")

# 표시 status 어휘.
STATUS_DISPLAY: dict[str, tuple[str, str]] = {
    "registered":    ("✅", "등록됨"),
    "untried":       ("·",  "미시도"),
    "pending":       ("⏳", "큐 대기"),
    "running":       ("🔁", "처리중"),
    "done":          ("✅", "완료 (config 부재 race)"),
    "gen_fail":      ("❌", "자동등록 실패"),
    "url_dead":      ("🔗", "URL 잘못/죽음"),
    "policy_reject": ("🚫", "정책 거부(로그인)"),
    "capability_blocked": ("🛡", "차단(능력 부족)"),
    "gate_reject":   ("🚫", "게이트 거부"),
    "bug":           ("🐞", "BUG"),
    "unknown":       ("⚠",  "분류 미스"),
}
STATUS_ORDER = [
    "untried", "pending", "running", "gen_fail", "url_dead", "policy_reject",
    "capability_blocked", "gate_reject", "bug", "unknown", "done", "registered",
]

_CATALOG_HEADER_TEMPLATE = """# {name} catalog — `scripts/register_batch.py --catalog={name}` 입력.
# (헤더는 dashboard add/remove 시 자동 재박음 — entry 안 inline 코멘트는 round-trip 시 소실.)
#
# 모델: docs/사이트 카탈로그 자동 등록 파이프라인 계획.md §2 (rev5 multi-file).

"""


# --------------------------------------------------------------------------- #
# Catalog I/O — multi-file
# --------------------------------------------------------------------------- #
def _catalog_path(name: str) -> Path:
    if not CATALOG_NAME_RE.match(name):
        raise HTTPException(status_code=400,
                            detail=f"invalid catalog name (regex {CATALOG_NAME_RE.pattern})")
    return CATALOG_DIR / f"{name}.yaml"


def _list_catalog_files() -> list[Path]:
    if not CATALOG_DIR.exists():
        return []
    return sorted(p for p in CATALOG_DIR.glob("*.yaml") if p.is_file())


def _load_catalog_doc(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        import yaml
    except ImportError:
        return None
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return None
    if not isinstance(doc, dict):
        return None
    return doc


def _entries_from(doc: Optional[dict]) -> list[dict]:
    if doc is None or doc.get("schema") != 2:
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


def _save_catalog_doc(path: Path, name: str, entries: list[dict]) -> None:
    try:
        import yaml
    except ImportError as e:
        raise RuntimeError("PyYAML 필요") from e
    payload = {"version": 1, "schema": 2, "entries": entries}
    yaml_text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False,
                                default_flow_style=False, width=200)
    full_text = _CATALOG_HEADER_TEMPLATE.format(name=name) + yaml_text
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".catalog_", suffix=".yaml", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(full_text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _all_urls_by_catalog() -> dict[str, str]:
    """url → catalog name. cross-catalog dedup 검증용."""
    out: dict[str, str] = {}
    for p in _list_catalog_files():
        for e in _entries_from(_load_catalog_doc(p)):
            out[e["url"]] = p.stem
    return out


# --------------------------------------------------------------------------- #
# Status classification (rev4 와 동일 로직)
# --------------------------------------------------------------------------- #
def _url_to_slug(url: str) -> str:
    from probe.paths import url_to_slug
    return url_to_slug(url)


def _canon(url: str) -> Optional[str]:
    try:
        from engine.slug import canonical_url
        return canonical_url(url)
    except Exception:  # noqa: BLE001
        return None


def _registered_alias_index() -> dict[str, str]:
    """canonical_url → 등록된 slug. snapshot poll_state 역조회.

    bot/site_ops.find_registered_alias 의 dashboard 판박이 (commit 0692a42). recognizer 추가/슬러그
    스키마 변경으로 같은 board URL 이 deploy 전후 다른 slug 를 받으면 `configs.snapshot/<새 slug>.json`
    부재 → 거짓 'done(race)' 로 보임. canonical 신원으로 기존 등록 slug 를 찾아 흡수한다.
    config 가 실제 존재하는 (등록된) slug 만 인덱싱.
    """
    state_dir = state.SNAPSHOT_DIR / "poll_state"
    if not state_dir.exists():
        return {}
    idx: dict[str, str] = {}
    for f in state_dir.glob("*.json"):
        nm = f.name
        if nm.endswith(".FAILED.json") or nm.endswith(".REJECTED.json"):
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8")) or {}
        except (json.JSONDecodeError, OSError):
            continue
        url = d.get("url")
        slug = d.get("slug") or nm[:-5]
        if not url or not (CONFIGS_SNAPSHOT / f"{slug}.json").exists():
            continue
        canon = _canon(url)
        if canon:
            idx[canon] = slug
    return idx


def _classify(slug: str, job_row: Optional[dict]) -> dict:
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
def _build_rows(entries: list[dict], jobs_by_url: dict[str, dict],
                alias_index: Optional[dict[str, str]] = None) -> list[dict]:
    alias_index = alias_index or {}
    out: list[dict] = []
    for e in entries:
        name = e["name"]
        url = e["url"]
        slug = _url_to_slug(url)
        via_alias = False
        # 슬러그 스키마 drift 흡수: computed slug 의 config 가 없으면 canonical 신원으로
        # 기존 등록 slug 채택 (bot find_registered_alias 와 동일 — 거짓 'done(race)' 방지).
        if not (CONFIGS_SNAPSHOT / f"{slug}.json").exists():
            canon = _canon(url)
            alias = alias_index.get(canon) if canon else None
            if alias and alias != slug:
                slug = alias
                via_alias = True
        cls = _classify(slug, jobs_by_url.get(url))
        if via_alias and cls["status"] == "registered":
            cls["subkind"] = "alias"
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
# Bulk URL parsing
# --------------------------------------------------------------------------- #
def _extract_urls(text: str) -> list[str]:
    """텍스트에서 http(s) URL 만 추출 + trailing punct 제거 + dedup (순서 유지)."""
    raw = URL_EXTRACT_RE.findall(text or "")
    out: list[str] = []
    seen: set[str] = set()
    for u in raw:
        # trailing punctuation cleanup — common around URLs in prose.
        while u and u[-1] in ".,);]>!?":
            u = u[:-1]
        if not (u.startswith("http://") or u.startswith("https://")):
            continue
        if len(u) > 1000:
            continue
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def _default_name_for(url: str) -> str:
    host = (urlparse(url).hostname or url)[:200]
    return host


# --------------------------------------------------------------------------- #
# Auto-naming for new catalog
# --------------------------------------------------------------------------- #
def _auto_catalog_name(today: Optional[_dt.date] = None) -> str:
    today = today or _dt.date.today()
    base = f"auto-{today.isoformat()}"
    existing = {p.stem for p in _list_catalog_files()}
    seq = 1
    while True:
        candidate = f"{base}-{seq}"
        if candidate not in existing:
            return candidate
        seq += 1


# --------------------------------------------------------------------------- #
# Per-catalog summary (index 표용)
# --------------------------------------------------------------------------- #
def _catalog_summary(path: Path, jobs_by_url: dict[str, dict],
                     alias_index: Optional[dict[str, str]] = None) -> dict:
    name = path.stem
    entries = _entries_from(_load_catalog_doc(path))
    rows = _build_rows(entries, jobs_by_url, alias_index)
    kpis = _kpis(rows)
    last_ts = ""
    for r in rows:
        if r["last_ts"] and r["last_ts"] > last_ts:
            last_ts = r["last_ts"]
    return {
        "name": name,
        "path": str(path.relative_to(ROOT)),
        "total": len(entries),
        "registered": kpis["registered"],
        "untried": kpis["untried"],
        "pending": kpis["pending"],
        "running": kpis["running"],
        "gen_fail": kpis["gen_fail"],
        "url_dead": kpis["url_dead"],
        "policy_reject": kpis["policy_reject"],
        "capability_blocked": kpis["capability_blocked"],
        "gate_reject": kpis["gate_reject"],
        "bug": kpis["bug"],
        "unknown": kpis["unknown"],
        "done": kpis["done"],
        "last_ts": last_ts,
        "progress_pct": (100 * (kpis["registered"] + kpis["done"]) // max(1, kpis["total"])),
    }


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
def register(app, templates, _render):  # noqa: ARG001

    @app.get("/candidates", response_class=HTMLResponse)
    async def candidates_index(request: Request):
        files = _list_catalog_files()
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

        alias_index = _registered_alias_index()
        catalogs = [_catalog_summary(p, jobs_by_url, alias_index) for p in files]
        catalogs.sort(key=lambda c: c["name"])

        # Aggregate KPI
        agg = {k: sum(c[k] for c in catalogs) for k in
               ("total", "registered", "untried", "pending", "running",
                "gen_fail", "url_dead", "policy_reject", "capability_blocked",
                "gate_reject", "bug", "unknown", "done")}

        return _render(
            "candidates_index.html", request,
            catalogs=catalogs,
            agg=agg,
            jobs_db_error=jobs_db_error,
            snapshot_ts=state.last_pull_str(),
            auto_name_preview=_auto_catalog_name(),
            status_display=STATUS_DISPLAY,
            active="candidates",
        )

    @app.get("/candidates/{name}", response_class=HTMLResponse)
    async def candidates_detail(
        name: str,
        request: Request,
        status: Optional[str] = Query(None),
        subkind: Optional[str] = Query(None),
        q: Optional[str] = Query(None),
    ):
        path = _catalog_path(name)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"catalog 없음: {name}")
        doc = _load_catalog_doc(path)
        entries = _entries_from(doc)

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

        all_rows = _build_rows(entries, jobs_by_url, _registered_alias_index())
        rows = _filter_rows(all_rows, status=status, subkind=subkind, q=q)
        rows.sort(key=lambda r: (STATUS_ORDER.index(r["status"])
                                  if r["status"] in STATUS_ORDER else 99,
                                  r["name"] or ""))
        kpis = _kpis(all_rows)
        distribution = _distribution(all_rows)
        all_statuses = sorted({r["status"] for r in all_rows})
        all_subkinds = sorted({r["subkind"] for r in all_rows if r["subkind"] not in ("—", "ok")})
        run_and_fix_prompt = prompts.catalog_run_and_fix(
            catalog_name=name,
            untried=kpis.get("untried", 0),
            failed=kpis.get("gen_fail", 0),
            bug=kpis.get("bug", 0),
        )
        return _render(
            "candidates_detail.html", request,
            catalog_name=name,
            run_and_fix_prompt=run_and_fix_prompt,
            rows=rows, kpis=kpis, distribution=distribution,
            jobs_db_error=jobs_db_error,
            total_filtered=len(rows), total_all=len(all_rows),
            facets={"statuses": all_statuses, "subkinds": all_subkinds},
            cur={"status": status or "", "subkind": subkind or "", "q": q or ""},
            status_display=STATUS_DISPLAY,
            status_order=STATUS_ORDER,
            catalog_path=str(path.relative_to(ROOT)),
            snapshot_ts=state.last_pull_str(),
            active="candidates",
        )

    @app.post("/candidates/{name}/edit", response_class=HTMLResponse)
    async def candidates_edit(
        name: str,
        old_url: str = Form(...),
        new_name: str = Form(...),
        new_url: str = Form(...),
    ):
        """행별 inline edit — name + url 동시 변경. yaml 의 같은 entry 교체."""
        path = _catalog_path(name)
        ou = (old_url or "").strip()
        nn = (new_name or "").strip()
        nu = (new_url or "").strip()
        if not ou or not nn or not nu:
            raise HTTPException(status_code=400, detail="old_url / new_name / new_url 다 필요")
        if len(nn) > 200:
            raise HTTPException(status_code=400, detail="name 200자 초과")
        if not (nu.startswith("http://") or nu.startswith("https://")) or len(nu) > 1000:
            raise HTTPException(status_code=400, detail="invalid new_url (http(s) 만, ≤1000자)")
        doc = _load_catalog_doc(path)
        if doc is None:
            raise HTTPException(status_code=500, detail="catalog 로드 실패")
        entries = doc.get("entries") or []
        idx = next((i for i, e in enumerate(entries)
                    if isinstance(e, dict) and e.get("url") == ou), -1)
        if idx < 0:
            raise HTTPException(status_code=404, detail=f"old_url 못 찾음: {ou}")
        if nu != ou:
            # within-file dup 검사
            if any(isinstance(e, dict) and e.get("url") == nu
                   for i, e in enumerate(entries) if i != idx):
                raise HTTPException(status_code=409, detail=f"new_url within-file 중복: {nu}")
            # cross-catalog dup 검사
            other = _all_urls_by_catalog().get(nu)
            if other and other != name:
                raise HTTPException(status_code=409,
                                    detail=f"new_url 다른 catalog 에 이미 있음: {other}")
        entries[idx] = {"name": nn, "url": nu}
        try:
            _save_catalog_doc(path, name, entries)
        except (OSError, RuntimeError) as e:
            raise HTTPException(status_code=500, detail=f"yaml 저장 실패: {e}")
        return RedirectResponse(url=f"/candidates/{name}", status_code=303)

    @app.post("/candidates/{name}/remove", response_class=HTMLResponse)
    async def candidates_remove(name: str, url: str = Form(...)):
        path = _catalog_path(name)
        u = (url or "").strip()
        if not u:
            raise HTTPException(status_code=400, detail="url 비어있음")
        doc = _load_catalog_doc(path)
        if doc is None:
            raise HTTPException(status_code=500, detail="catalog 로드 실패")
        entries = doc.get("entries") or []
        before = len(entries)
        new_entries = [e for e in entries
                       if not (isinstance(e, dict) and e.get("url") == u)]
        if len(new_entries) == before:
            raise HTTPException(status_code=404, detail=f"url 못 찾음: {u}")
        try:
            _save_catalog_doc(path, name, new_entries)
        except (OSError, RuntimeError) as e:
            raise HTTPException(status_code=500, detail=f"yaml 저장 실패: {e}")
        return RedirectResponse(url=f"/candidates/{name}", status_code=303)

    @app.post("/candidates/{name}/add-bulk", response_class=HTMLResponse)
    async def candidates_add_bulk(name: str, bulk_text: str = Form(...)):
        path = _catalog_path(name)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"catalog 없음: {name}")
        urls = _extract_urls(bulk_text)
        if not urls:
            raise HTTPException(status_code=400, detail="URL 못 찾음 (http(s):// 문자열 없음)")
        doc = _load_catalog_doc(path)
        if doc is None:
            raise HTTPException(status_code=500, detail="catalog 로드 실패")
        entries = doc.get("entries") or []
        existing_urls = {e.get("url") for e in entries if isinstance(e, dict)}
        cross_urls = _all_urls_by_catalog()
        added = 0
        skipped_dup_within = 0
        skipped_dup_cross = []
        for u in urls:
            if u in existing_urls:
                skipped_dup_within += 1
                continue
            other = cross_urls.get(u)
            if other and other != name:
                skipped_dup_cross.append((u, other))
                continue
            entries.append({"name": _default_name_for(u), "url": u})
            existing_urls.add(u)
            added += 1
        if added == 0:
            detail = f"새 URL 0개 추가됨 (within-file dup {skipped_dup_within}, cross-file dup {len(skipped_dup_cross)})"
            raise HTTPException(status_code=409, detail=detail)
        try:
            _save_catalog_doc(path, name, entries)
        except (OSError, RuntimeError) as e:
            raise HTTPException(status_code=500, detail=f"yaml 저장 실패: {e}")
        return RedirectResponse(url=f"/candidates/{name}", status_code=303)

    @app.post("/candidates/new", response_class=HTMLResponse)
    async def candidates_new(name: str = Form(""), bulk_text: str = Form("")):
        nm = (name or "").strip().lower()
        if not nm:
            nm = _auto_catalog_name()
        if not CATALOG_NAME_RE.match(nm):
            raise HTTPException(status_code=400,
                                detail=f"invalid catalog name (regex {CATALOG_NAME_RE.pattern}): {nm!r}")
        path = CATALOG_DIR / f"{nm}.yaml"
        if path.exists():
            raise HTTPException(status_code=409, detail=f"catalog 이미 존재: {nm}")
        urls = _extract_urls(bulk_text)
        cross_urls = _all_urls_by_catalog()
        entries: list[dict] = []
        skipped_dup_cross = []
        seen_within: set[str] = set()
        for u in urls:
            if u in seen_within:
                continue
            other = cross_urls.get(u)
            if other:
                skipped_dup_cross.append((u, other))
                continue
            entries.append({"name": _default_name_for(u), "url": u})
            seen_within.add(u)
        try:
            _save_catalog_doc(path, nm, entries)
        except (OSError, RuntimeError) as e:
            raise HTTPException(status_code=500, detail=f"yaml 저장 실패: {e}")
        return RedirectResponse(url=f"/candidates/{nm}", status_code=303)
