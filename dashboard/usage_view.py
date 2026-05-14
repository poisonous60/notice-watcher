"""`output/snapshot/usage.sqlite3` (pull 로 가져온 사본) 위 read-only 집계 헬퍼.

dashboard/app.py 의 `/usage` 라우트가 사용. 모든 함수는 connection·since(iso) 만 받음 →
다른 caller(예: CLI 보고서) 에서도 재사용 가능.

집계 단위:
- KPIs    : 합계/평균
- Matrix  : (call_site × model) 카운트/토큰/비용
- Recent  : 최근 N행 raw
- Series  : 일별 토큰 합 (call_site 컬러 별) — chart.js 입력
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


def open_usage_conn(path: Path) -> Optional[sqlite3.Connection]:
    if not path.exists():
        return None
    conn = sqlite3.connect(str(path), timeout=15.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def since_iso_for(range_key: str) -> Optional[str]:
    """range_key → since 절단 시각(UTC ISO). `all` 이면 None."""
    now = datetime.now(timezone.utc)
    if range_key == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")
    if range_key == "7d":
        return (now - timedelta(days=7)).isoformat(timespec="seconds")
    if range_key == "30d":
        return (now - timedelta(days=30)).isoformat(timespec="seconds")
    return None  # all


def _where_clause(since_iso: Optional[str], call_site: Optional[str]) -> tuple[str, list]:
    parts = []
    params: list = []
    if since_iso:
        parts.append("ts >= ?")
        params.append(since_iso)
    if call_site:
        parts.append("call_site = ?")
        params.append(call_site)
    if not parts:
        return "", []
    return " WHERE " + " AND ".join(parts), params


def usage_kpis(conn: sqlite3.Connection, *, since_iso: Optional[str],
               call_site: Optional[str] = None) -> dict:
    where, params = _where_clause(since_iso, call_site)
    q = f"""
        SELECT
          COUNT(*)                                  AS n_calls,
          COALESCE(SUM(prompt_tokens), 0)           AS prompt_tokens,
          COALESCE(SUM(completion_tokens), 0)       AS completion_tokens,
          COALESCE(SUM(total_tokens), 0)            AS total_tokens,
          COALESCE(SUM(cost_usd), 0.0)              AS cost_usd,
          COALESCE(AVG(latency_ms), 0.0)            AS avg_latency_ms,
          SUM(CASE WHEN status = 'ok' THEN 0 ELSE 1 END) AS n_errors
        FROM llm_calls
        {where}
    """
    row = conn.execute(q, params).fetchone()
    if row is None:
        return {"n_calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
                "total_tokens": 0, "cost_usd": 0.0, "avg_latency_ms": 0.0,
                "n_errors": 0, "error_rate_pct": 0.0}
    d = dict(row)
    d["error_rate_pct"] = (100.0 * d["n_errors"] / d["n_calls"]) if d["n_calls"] else 0.0
    return d


def usage_matrix(conn: sqlite3.Connection, *, since_iso: Optional[str]) -> list[dict]:
    where, params = _where_clause(since_iso, None)
    q = f"""
        SELECT
          call_site,
          provider,
          model,
          COUNT(*)                            AS n_calls,
          COALESCE(SUM(prompt_tokens), 0)     AS prompt_tokens,
          COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
          COALESCE(SUM(total_tokens), 0)      AS total_tokens,
          COALESCE(SUM(cost_usd), 0.0)        AS cost_usd,
          COALESCE(AVG(latency_ms), 0.0)      AS avg_latency_ms,
          SUM(CASE WHEN status = 'ok' THEN 0 ELSE 1 END) AS n_errors
        FROM llm_calls
        {where}
        GROUP BY call_site, provider, model
        ORDER BY call_site, n_calls DESC
    """
    return [dict(r) for r in conn.execute(q, params).fetchall()]


def usage_recent(conn: sqlite3.Connection, *, since_iso: Optional[str],
                 call_site: Optional[str], limit: int = 100) -> list[dict]:
    where, params = _where_clause(since_iso, call_site)
    q = f"""
        SELECT id, ts, call_site, slug, attempt, provider, model, status,
               prompt_tokens, completion_tokens, total_tokens,
               latency_ms, cost_usd, key_idx, raw_model
        FROM llm_calls
        {where}
        ORDER BY ts DESC, id DESC
        LIMIT ?
    """
    return [dict(r) for r in conn.execute(q, params + [int(limit)]).fetchall()]


def usage_daily_series(conn: sqlite3.Connection, *, days: int = 14) -> dict:
    """일별 (call_site → tokens) 시계열. chart.js 입력 형태로 반환.

    Returns: {"labels": [YYYY-MM-DD,...], "datasets": [{"label": call_site, "data": [N, N, ...]}, ...]}
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    q = """
        SELECT substr(ts, 1, 10) AS day, call_site,
               COALESCE(SUM(total_tokens), 0) AS tokens
        FROM llm_calls
        WHERE ts >= ?
        GROUP BY day, call_site
        ORDER BY day, call_site
    """
    rows = conn.execute(q, [since]).fetchall()
    # 라벨 = 최근 days 개 날짜 (빈 날도 포함)
    today = datetime.now(timezone.utc).date()
    labels = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    sites: dict[str, dict[str, int]] = {}
    for r in rows:
        sites.setdefault(r["call_site"], {})[r["day"]] = int(r["tokens"])
    datasets = []
    for site, by_day in sorted(sites.items()):
        datasets.append({
            "label": site,
            "data": [by_day.get(d, 0) for d in labels],
        })
    return {"labels": labels, "datasets": datasets}


def list_call_sites(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT DISTINCT call_site FROM llm_calls ORDER BY call_site").fetchall()
    return [r[0] for r in rows]
