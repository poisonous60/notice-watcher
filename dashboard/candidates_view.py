"""`/candidates` 라우트 — 사이트 카탈로그 등록 시도 분포.

`configs/candidates/catalog.yaml` (catalog) + `output/register_batch_runs.sqlite3`
(runs) + 로컬 configs/poll_state state file 을 join 해 카테고리 × tier × 결과
분포를 표시. dev box 전용. N100 안 봄.

설계: `docs/사이트 카탈로그 자동 등록 파이프라인 계획.md` §6.

라우트:
  GET /candidates                — KPI + 카테고리×tier matrix + 상세 표
  GET /candidates?category=…&tier=A,B&status=…&provenance=…&q=…
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from dashboard import state

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "configs" / "candidates" / "catalog.yaml"
RUNS_DB_PATH = ROOT / "output" / "register_batch_runs.sqlite3"
CONFIGS_DIR = ROOT / "configs"
CONFIGS_SNAPSHOT = ROOT / "configs.snapshot"
STATE_DIR = ROOT / "output" / "poll_state"
SNAPSHOT_STATE_DIR = ROOT / "output" / "snapshot" / "poll_state"

# enum 정렬 키 (display 용)
CATEGORY_ORDER = [
    "kr-game-official", "global-game-official", "kr-community-open",
    "kr-community-blocked", "kr-community-login", "global-community",
    "forum-engine", "global-game-store", "social-media", "news-wiki",
]
TIER_ORDER = ["A", "B", "C", "D", "E", "F", "G"]
STATUS_DISPLAY = {
    "registered":         ("✅", "등록 성공"),
    "already_registered": ("✅", "이미 등록"),
    "failed":             ("❌", "자동등록 실패"),
    "policy_rejected":    ("🚫", "정책 거부"),
    "gate_rejected":      ("🚫", "게이트 거부"),
    "already_rejected":   ("🚫", "이미 거부"),
    "bug_marked":         ("🐞", "BUG 마커"),
    "recent_fail_skip":   ("⏳", "최근 실패 cooldown"),
    "triage_later":       ("⏸", "나중에"),
    "timeout":            ("⌛", "timeout"),
    "untried":            ("·",  "미시도"),
    "error_cli":          ("⚠",  "CLI 오류"),
    "error_no_config":    ("⚠",  "config 부재"),
    "error_runtime":      ("⚠",  "런타임 오류"),
    "error_unexpected":   ("⚠",  "예상외 rc"),
}


def _load_catalog_doc() -> Optional[dict]:
    """yaml 전체 doc (version + schema + entries) 반환. 실패 시 None."""
    if not CATALOG_PATH.exists():
        return None
    try:
        import yaml  # 지연 import — dashboard 시작에 강요 X
    except ImportError:
        return None
    try:
        doc = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return None
    if not isinstance(doc, dict):
        return None
    return doc


def _load_catalog() -> list[dict]:
    """yaml 안전 로드. 실패 시 빈 리스트 (라우트가 안내)."""
    doc = _load_catalog_doc()
    if doc is None:
        return []
    entries = doc.get("entries") or []
    return [e for e in entries if isinstance(e, dict)]


# Header that auto-replaces on every catalog write (PyYAML 가 round-trip 시 comment 소실 →
# 코드가 다시 박음). 본문은 entries 만 데이터 — 사람이 직접 yaml 편집해도 됨.
_CATALOG_HEADER = """# 사이트 카탈로그 — `scripts/register_batch.py` 입력.
# (이 헤더는 dashboard 의 add/remove 시 자동 재박음 — entry 안 inline 코멘트는 round-trip 시 소실.)
#
# 스키마: docs/사이트 카탈로그 자동 등록 파이프라인 계획.md §3.
# tier: A=정적HTML B=서버렌더+hydration C=SPA+JSON D=auth E=Heavy SPA+bot F=iframe G=CAPTCHA.
# expected_strategy: rss | httpx_json | httpx_html | playwright_html | handwritten | unknown.
# provenance: doc | history | web.

"""


def _save_catalog_doc(doc: dict) -> None:
    """yaml atomic write. version + schema 보존, entries 재serialize."""
    try:
        import yaml
    except ImportError as e:
        raise RuntimeError("PyYAML 필요") from e
    payload = {
        "version": doc.get("version", 1),
        "schema": doc.get("schema", 1),
        "entries": doc.get("entries") or [],
    }
    yaml_text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False,
                                default_flow_style=False, width=120)
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


# Enum 검증 (register_batch.py 와 동기) — POST add 시 사용.
_ALLOWED_CATEGORIES = {
    "global-game-store", "global-game-official", "kr-game-official",
    "global-community", "forum-engine", "kr-community-open",
    "kr-community-blocked", "kr-community-login", "social-media", "news-wiki",
}
_ALLOWED_TIERS = {"A", "B", "C", "D", "E", "F", "G"}
_ALLOWED_STRATEGIES = {
    "rss", "httpx_json", "httpx_html", "playwright_html", "handwritten", "unknown",
}
_ALLOWED_PROVENANCE = {"doc", "history", "web"}

# cand_id allowlist — 파일/URL 안 들어가는 문자만.
import re as _re
_CAND_ID_RE = _re.compile(r"^[A-Za-z0-9._\-]{1,80}$")


def _open_runs_conn() -> Optional[sqlite3.Connection]:
    if not RUNS_DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(str(RUNS_DB_PATH), timeout=15.0, check_same_thread=False)
    except sqlite3.Error:
        return None
    conn.row_factory = sqlite3.Row
    return conn


def _latest_runs_by_url(conn: sqlite3.Connection) -> tuple[dict[str, dict], Optional[str]]:
    """url → 가장 최신 row (dict) + 오류 메시지 (있으면). 같은 url 의 과거 row 는 묻힘.

    runs 테이블이 같은 url 여러 번 가질 수 있어 GROUP BY 로 최신만.
    sqlite 오류 시 빈 dict + 오류 메시지 — 라우트가 사용자에게 경고로 띄움 (codex
    review #5 SHOULD-FIX 반영).
    """
    out: dict[str, dict] = {}
    try:
        rows = conn.execute(
            """SELECT r.* FROM runs r
               INNER JOIN (
                   SELECT url, MAX(ts) AS max_ts FROM runs GROUP BY url
               ) m ON r.url = m.url AND r.ts = m.max_ts"""
        ).fetchall()
    except sqlite3.Error as e:
        return out, f"sqlite 오류: {type(e).__name__}: {e}"
    for r in rows:
        out[r["url"]] = dict(r)
    return out, None


def _fs_status_for_slug(slug: str) -> Optional[str]:
    """파일 시스템만 보고 'already_registered' / 'already_rejected' / 'bug_marked' 결정.

    runs DB 가 비어있어도 (사용자가 batch 안 돌렸어도) 봇 `/watch` 로 등록된 사이트
    catalog 에 잡힘. dev box `configs/` + N100 snapshot 양쪽 다 본다 (codex review #5
    SHOULD-FIX 반영 — batch driver 와 동일한 idempotency 시야 보장).
    """
    if ((CONFIGS_DIR / f"{slug}.json").exists()
            or (CONFIGS_SNAPSHOT / f"{slug}.json").exists()):
        return "already_registered"
    if ((STATE_DIR / f"{slug}.REJECTED.json").exists()
            or (SNAPSHOT_STATE_DIR / f"{slug}.REJECTED.json").exists()):
        return "already_rejected"
    if ((STATE_DIR / f"{slug}.BUG.json").exists()
            or (SNAPSHOT_STATE_DIR / f"{slug}.BUG.json").exists()):
        return "bug_marked"
    if ((STATE_DIR / f"{slug}.FAILED.json").exists()
            or (SNAPSHOT_STATE_DIR / f"{slug}.FAILED.json").exists()):
        return "failed"
    return None


def _url_to_slug(url: str) -> str:
    """probe.paths.url_to_slug 호출 — dashboard 시작 시 import 안 하려고 지연."""
    from probe.paths import url_to_slug
    return url_to_slug(url)


def _build_rows(entries: list[dict], runs_by_url: dict[str, dict]) -> list[dict]:
    """entry × board → 표 행. 우선순위: runs 최신 > 파일시스템 status > untried.

    동기 I/O 주의 (codex review #4 SHOULD-FIX): per-board `Path.exists()` + json 읽기.
    47 entry · 로컬 SSD 기준 5~20ms — async handler 안에서 허용. 카탈로그 ≥ 200 으로 커지면
    `asyncio.to_thread` 로 감싸야 함.
    """
    out: list[dict] = []
    for e in entries:
        cat = e.get("category", "")
        tier = e.get("tier", "")
        prov = (e.get("source") or {}).get("provenance") or ""
        for b in (e.get("boards") or []):
            url = b.get("url") or ""
            label = b.get("label") or ""
            slug = _url_to_slug(url)
            run = runs_by_url.get(url)
            status = None
            reason = ""
            actual_strategy = None
            actual_adapter = None
            last_ts = ""
            duration = None
            rc = None
            if run:
                status = run.get("status")
                reason = run.get("reason") or ""
                actual_strategy = run.get("actual_strategy")
                actual_adapter = run.get("actual_adapter")
                last_ts = (run.get("ts") or "")[:19]
                duration = run.get("duration_s")
                rc = run.get("rc")
            if not status:
                fs = _fs_status_for_slug(slug)
                if fs:
                    status = fs
                    # config 의 strategy 도 확인 — actual_strategy 채움
                    if fs == "already_registered":
                        for cfg_path in (CONFIGS_DIR / f"{slug}.json",
                                          CONFIGS_SNAPSHOT / f"{slug}.json"):
                            if not cfg_path.exists():
                                continue
                            try:
                                import json
                                d = json.loads(cfg_path.read_text(encoding="utf-8"))
                                actual_strategy = d.get("strategy")
                                actual_adapter = d.get("adapter")
                                break
                            except (OSError, ValueError):
                                continue
                else:
                    status = "untried"
            emoji, label_ko = STATUS_DISPLAY.get(status, ("?", status or "?"))
            out.append({
                "cand_id": e.get("id"),
                "name": e.get("name") or e.get("id"),
                "category": cat,
                "tier": tier,
                "provenance": prov,
                "expected_strategy": e.get("expected_strategy"),
                "actual_strategy": actual_strategy,
                "actual_adapter": actual_adapter,
                "strategy_mismatch": (
                    bool(actual_strategy)
                    and actual_strategy != e.get("expected_strategy")
                    and e.get("expected_strategy") != "unknown"
                ),
                "url": url,
                "label": label,
                "slug": slug,
                "status": status,
                "status_emoji": emoji,
                "status_label": label_ko,
                "reason": reason,
                "last_ts": last_ts,
                "duration_s": duration,
                "rc": rc,
                "note": e.get("note") or "",
                "source_section": (e.get("source") or {}).get("section") or "",
            })
    return out


def _filter_rows(rows: list[dict], *, category, tier, status, provenance, q) -> list[dict]:
    out = rows
    if category:
        cats = {x.strip() for x in category.split(",") if x.strip()}
        out = [r for r in out if r["category"] in cats]
    if tier:
        tiers = {x.strip() for x in tier.split(",") if x.strip()}
        out = [r for r in out if r["tier"] in tiers]
    if status:
        statuses = {x.strip() for x in status.split(",") if x.strip()}
        out = [r for r in out if r["status"] in statuses]
    if provenance:
        provs = {x.strip() for x in provenance.split(",") if x.strip()}
        out = [r for r in out if r["provenance"] in provs]
    if q:
        ql = q.strip().lower()
        out = [r for r in out
               if ql in (r["cand_id"] or "").lower()
               or ql in (r["name"] or "").lower()
               or ql in (r["url"] or "").lower()
               or ql in (r["slug"] or "").lower()]
    return out


def _kpis(rows: list[dict]) -> dict[str, int]:
    """전체 분포 — 정렬용 status groups."""
    out = {
        "total": len(rows),
        "registered": 0,
        "rejected": 0,
        "failed": 0,
        "untried": 0,
        "skipped": 0,
        "error": 0,
    }
    for r in rows:
        s = r["status"]
        if s in ("registered", "already_registered"):
            out["registered"] += 1
        elif s in ("policy_rejected", "gate_rejected", "already_rejected"):
            out["rejected"] += 1
        elif s in ("failed", "timeout"):
            out["failed"] += 1
        elif s == "untried":
            out["untried"] += 1
        elif s in ("recent_fail_skip", "triage_later", "bug_marked"):
            out["skipped"] += 1
        else:
            out["error"] += 1
    return out


def _matrix(rows: list[dict]) -> list[dict]:
    """category × tier 매트릭스. 각 셀 = {total, registered, rejected, failed, untried}."""
    grid: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["category"], r["tier"])
        cell = grid.setdefault(key, {"total": 0, "registered": 0, "rejected": 0,
                                     "failed": 0, "untried": 0})
        cell["total"] += 1
        s = r["status"]
        if s in ("registered", "already_registered"):
            cell["registered"] += 1
        elif s in ("policy_rejected", "gate_rejected", "already_rejected"):
            cell["rejected"] += 1
        elif s in ("failed", "timeout"):
            cell["failed"] += 1
        elif s == "untried":
            cell["untried"] += 1
    # category 별 row 묶기 — 보이는 카테고리만 (rows 에 있는 것만)
    cats_present = [c for c in CATEGORY_ORDER if any(r["category"] == c for r in rows)]
    cats_present += sorted({r["category"] for r in rows} - set(CATEGORY_ORDER))
    out = []
    for cat in cats_present:
        cells = []
        cat_total = 0
        cat_registered = 0
        for tier in TIER_ORDER:
            cell = grid.get((cat, tier)) or {"total": 0, "registered": 0,
                                              "rejected": 0, "failed": 0, "untried": 0}
            cells.append({"tier": tier, **cell})
            cat_total += cell["total"]
            cat_registered += cell["registered"]
        out.append({"category": cat, "cells": cells,
                    "total": cat_total, "registered": cat_registered})
    return out


def register(app, templates, _render):  # noqa: ARG001 (templates 인자는 mirror)
    @app.get("/candidates", response_class=HTMLResponse)
    async def candidates_page(
        request: Request,
        category: Optional[str] = Query(None),
        tier: Optional[str] = Query(None),
        status: Optional[str] = Query(None),
        provenance: Optional[str] = Query(None),
        q: Optional[str] = Query(None),
    ):
        entries = _load_catalog()
        catalog_warning = None
        if not entries:
            if CATALOG_PATH.exists():
                catalog_warning = (
                    f"카탈로그 ({CATALOG_PATH.relative_to(ROOT)}) 가 비어있거나 "
                    "YAML 파싱 실패. `python -c 'import yaml; yaml.safe_load(open(...))'` 로 점검."
                )
            else:
                catalog_warning = (
                    f"카탈로그 파일 없음: {CATALOG_PATH.relative_to(ROOT)}. "
                    "`docs/사이트 카탈로그 자동 등록 파이프라인 계획.md` §3 참고."
                )
        runs_by_url: dict[str, dict] = {}
        runs_db_error: Optional[str] = None
        conn = _open_runs_conn()
        if conn is not None:
            try:
                runs_by_url, runs_db_error = _latest_runs_by_url(conn)
            finally:
                conn.close()
        all_rows = _build_rows(entries, runs_by_url)
        rows = _filter_rows(
            all_rows, category=category, tier=tier, status=status,
            provenance=provenance, q=q,
        )
        # 정렬: 상태 (untried 먼저 — 행동 우선) > category > tier > id
        status_priority = {
            "untried": 0, "failed": 1, "timeout": 1, "error_cli": 1, "error_runtime": 1,
            "error_no_config": 1, "error_unexpected": 1, "bug_marked": 1,
            "recent_fail_skip": 2, "triage_later": 2,
            "policy_rejected": 3, "gate_rejected": 3, "already_rejected": 3,
            "registered": 4, "already_registered": 4,
        }
        rows.sort(key=lambda r: (status_priority.get(r["status"], 9),
                                 CATEGORY_ORDER.index(r["category"])
                                 if r["category"] in CATEGORY_ORDER else 99,
                                 r["tier"], r["cand_id"] or ""))
        kpis = _kpis(all_rows)
        matrix = _matrix(all_rows)
        # facet 옵션 (드롭다운/체크박스 용)
        all_categories = [c for c in CATEGORY_ORDER if any(e.get("category") == c for e in entries)]
        all_categories += sorted({e.get("category", "") for e in entries} - set(all_categories) - {""})
        all_tiers = [t for t in TIER_ORDER if any(e.get("tier") == t for e in entries)]
        all_statuses = sorted({r["status"] for r in all_rows})
        all_provenances = sorted({r["provenance"] for r in all_rows if r["provenance"]})
        return _render(
            "candidates.html", request,
            rows=rows, kpis=kpis, matrix=matrix,
            catalog_warning=catalog_warning,
            runs_db_error=runs_db_error,
            total_filtered=len(rows), total_all=len(all_rows),
            facets={
                "categories": all_categories, "tiers": all_tiers,
                "statuses": all_statuses, "provenances": all_provenances,
            },
            cur={
                "category": category or "", "tier": tier or "",
                "status": status or "", "provenance": provenance or "",
                "q": q or "",
            },
            status_display=STATUS_DISPLAY,
            catalog_path=str(CATALOG_PATH.relative_to(ROOT)),
            runs_db_present=RUNS_DB_PATH.exists(),
            allowed_categories=sorted(_ALLOWED_CATEGORIES),
            allowed_tiers=sorted(_ALLOWED_TIERS),
            allowed_strategies=sorted(_ALLOWED_STRATEGIES),
            allowed_provenance=sorted(_ALLOWED_PROVENANCE),
            active="candidates",
        )

    # --------------------------------------------------------------------- #
    # 카탈로그 mutate — entry 제거 / 추가. catalog.yaml 직접 write.
    # --------------------------------------------------------------------- #
    @app.post("/candidates/remove", response_class=HTMLResponse)
    async def candidates_remove(cand_id: str = Form(...)):
        cid = (cand_id or "").strip()
        if not _CAND_ID_RE.match(cid):
            raise HTTPException(status_code=400, detail="invalid cand_id")
        doc = _load_catalog_doc()
        if doc is None:
            raise HTTPException(status_code=500, detail="catalog 로드 실패")
        entries = doc.get("entries") or []
        before = len(entries)
        doc["entries"] = [e for e in entries if e.get("id") != cid]
        if len(doc["entries"]) == before:
            raise HTTPException(status_code=404, detail=f"cand_id={cid!r} 못 찾음")
        try:
            _save_catalog_doc(doc)
        except (OSError, RuntimeError) as e:
            raise HTTPException(status_code=500, detail=f"yaml 저장 실패: {e}")
        return RedirectResponse(url="/candidates", status_code=303)

    @app.post("/candidates/add", response_class=HTMLResponse)
    async def candidates_add(
        cand_id: str = Form(...),
        name: str = Form(...),
        category: str = Form(...),
        tier: str = Form(...),
        expected_strategy: str = Form(...),
        url: str = Form(...),
        label: str = Form(""),
        note: str = Form(""),
        provenance: str = Form("web"),
        source_section: str = Form(""),
    ):
        cid = (cand_id or "").strip()
        if not _CAND_ID_RE.match(cid):
            raise HTTPException(status_code=400, detail="invalid cand_id (영숫자 . _ -, ≤80자)")
        nm = (name or "").strip()
        if not nm or len(nm) > 200:
            raise HTTPException(status_code=400, detail="invalid name (1~200자)")
        if category not in _ALLOWED_CATEGORIES:
            raise HTTPException(status_code=400, detail=f"invalid category — 허용: {sorted(_ALLOWED_CATEGORIES)}")
        if tier not in _ALLOWED_TIERS:
            raise HTTPException(status_code=400, detail="invalid tier (A~G)")
        if expected_strategy not in _ALLOWED_STRATEGIES:
            raise HTTPException(status_code=400, detail=f"invalid expected_strategy — 허용: {sorted(_ALLOWED_STRATEGIES)}")
        if provenance not in _ALLOWED_PROVENANCE:
            raise HTTPException(status_code=400, detail="invalid provenance (doc/history/web)")
        u = (url or "").strip()
        if not (u.startswith("http://") or u.startswith("https://")) or len(u) > 1000:
            raise HTTPException(status_code=400, detail="invalid url (http(s) 만, ≤1000자)")
        doc = _load_catalog_doc()
        if doc is None:
            raise HTTPException(status_code=500, detail="catalog 로드 실패")
        entries = doc.get("entries") or []
        if any(e.get("id") == cid for e in entries):
            raise HTTPException(status_code=409, detail=f"cand_id 중복: {cid}")
        existing_urls = {b.get("url") for e in entries for b in (e.get("boards") or []) if isinstance(b, dict)}
        if u in existing_urls:
            raise HTTPException(status_code=409, detail=f"url 중복: {u}")
        new_entry = {
            "id": cid,
            "name": nm,
            "category": category,
            "tier": tier,
            "expected_strategy": expected_strategy,
            "boards": [{"url": u, "label": (label or "").strip() or "main"}],
            "source": {
                "doc": "dashboard add",
                "section": (source_section or "").strip() or "manual",
                "provenance": provenance,
            },
        }
        if (note or "").strip():
            new_entry["note"] = note.strip()
        doc["entries"] = entries + [new_entry]
        try:
            _save_catalog_doc(doc)
        except (OSError, RuntimeError) as e:
            raise HTTPException(status_code=500, detail=f"yaml 저장 실패: {e}")
        return RedirectResponse(url="/candidates", status_code=303)
