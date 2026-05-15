"""`/users` 페이지 — person-entity 집계·필터·정렬 헬퍼.

snapshot 의 bot.sqlite3 만 본다(read-only). 액션(M1/M2/M3·scoped announce)은
`dashboard.control_actions` 의 SSH path 로 분리. 여기는 표시 전용.

설계:
  - DB 측 집계 = `bot.db.list_users / get_user / deliveries_for_target`.
  - 필터/정렬은 메모리상에서 (user 수가 수십~수백 수준이라 풀스캔 OK; pagination 단순).
  - column 가시성 토글은 client-side localStorage — 서버에서 신경 안 씀.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from bot import db


_VALID_SORTS = {
    "user_id", "username", "n_subs", "n_dm_subs", "n_channel_subs",
    "n_feedback", "n_reports_open", "n_reports_total",
    "first_seen", "last_active", "total_deliveries", "last_delivery_at",
}


def _sort_key(row: dict, col: str):
    """None 안전 — None 은 정렬 끝으로."""
    v = row.get(col)
    if v is None:
        # 숫자 컬럼은 -1, 문자열은 빈 문자열 — descending 시 None 이 항상 뒤로 가도록 변환.
        if col.startswith("n_") or col == "total_deliveries":
            return -1
        return ""
    return v


def collect(conn: sqlite3.Connection, *,
            q: Optional[str] = None,
            slug_filter: Optional[str] = None,
            chip_open_report: bool = False,
            chip_has_feedback: bool = False,
            chip_has_channel: bool = False,
            sort: str = "last_active",
            direction: str = "desc") -> list[dict]:
    """필터+정렬된 사용자 목록 반환 (한 행 = 한 사용자 + 집계)."""
    users = db.list_users(conn)

    # slug_filter: 그 slug 를 어떤 형태로든 구독한 user 만 (DM/channel 무관).
    slug_user_ids: Optional[set[str]] = None
    if slug_filter:
        rows = conn.execute(
            "SELECT DISTINCT user_id FROM subscriptions WHERE slug=?",
            (slug_filter,),
        ).fetchall()
        slug_user_ids = {r[0] for r in rows}

    def _match(u: dict) -> bool:
        if q:
            ql = q.strip().lower()
            uid = (u.get("user_id") or "").lower()
            uname = (u.get("username") or "").lower()
            if ql not in uid and ql not in uname:
                return False
        if chip_open_report and (u.get("n_reports_open") or 0) <= 0:
            return False
        if chip_has_feedback and (u.get("n_feedback") or 0) <= 0:
            return False
        if chip_has_channel and (u.get("n_channel_subs") or 0) <= 0:
            return False
        if slug_user_ids is not None and u["user_id"] not in slug_user_ids:
            return False
        return True

    filtered = [u for u in users if _match(u)]

    col = sort if sort in _VALID_SORTS else "last_active"
    reverse = (direction or "desc").lower() != "asc"
    filtered.sort(key=lambda u: _sort_key(u, col), reverse=reverse)
    return filtered


def detail(conn: sqlite3.Connection, user_id: str) -> Optional[dict]:
    """단일 user 상세 + DM/channel 구독 분리."""
    u = db.get_user(conn, user_id)
    if u is None:
        return None
    subs = u.pop("subscriptions", [])
    u["dm_subs"] = [s for s in subs if s.get("target_kind") == "dm"]
    u["channel_subs"] = [s for s in subs if s.get("target_kind") == "channel"]
    return u


def deliveries_inline(conn: sqlite3.Connection, *, target_id: str, slug: str,
                      limit: int = 50) -> list[dict]:
    """detail 페이지의 expandable 발송 이력 (특정 slug + 특정 target)."""
    return [dict(r) for r in db.deliveries_for_target(
        conn, target_id, slug=slug, limit=limit)]


def seen_post_ids(state_dir, slug: str) -> set[str]:
    """preview modal 의 'seen 에서 evict 됐는지' 경고용 — snapshot 의 poll_state JSON 읽기.

    실패 시 빈 set 반환 (보수적: '확인 불가, 모름' 으로 취급).
    """
    import json
    p = state_dir / f"{slug}.json"
    if not p.exists():
        return set()
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {str(x) for x in (d.get("seen_post_ids") or [])}
