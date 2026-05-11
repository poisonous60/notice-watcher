"""SQLite — 봇 구독 정보 + 다이제스트 대기열 + 발송 기록.

DB 파일: output/bot.sqlite3 (이미 .gitignore 됨).
필터 프롬프트·발송 대상·스케줄은 *여기에만* 산다 (configs/ · poll_state/ 엔 절대 안 씀).

테이블:
  subscriptions(user_id, slug, url, filter_prompt, schedule, target_kind, target_id, created_at)
      schedule = 'realtime' (폴링 때마다 바로) | 'HH:MM' (KST, 그 시각에 하루치 다이제스트)
      target_kind = 'dm' (target_id = user_id) | 'channel' (target_id = channel_id)
      UNIQUE(user_id, slug, target_id) → /watch 멱등
  pending(slug, post_id, target_id, summary, found_at)   다이제스트 구독자용 outbox (필터 통과+요약 완료, 아직 미발송)
      UNIQUE(slug, post_id, target_id)
  deliveries(slug, post_id, target_id, sent_at)          이미 보낸 (slug,post_id,target_id) — 다시 안 보냄
      PRIMARY KEY(slug, post_id, target_id)
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent.parent / "output" / "bot.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS subscriptions (
    id           INTEGER PRIMARY KEY,
    user_id      TEXT NOT NULL,
    slug         TEXT NOT NULL,
    url          TEXT NOT NULL,
    filter_prompt TEXT,
    schedule     TEXT NOT NULL DEFAULT 'realtime',
    target_kind  TEXT NOT NULL CHECK (target_kind IN ('dm','channel')),
    target_id    TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    UNIQUE(user_id, slug, target_id)
);
CREATE INDEX IF NOT EXISTS idx_subs_slug ON subscriptions(slug);
CREATE INDEX IF NOT EXISTS idx_subs_user ON subscriptions(user_id);

CREATE TABLE IF NOT EXISTS pending (
    id        INTEGER PRIMARY KEY,
    slug      TEXT NOT NULL,
    post_id   TEXT NOT NULL,
    target_id TEXT NOT NULL,
    summary   TEXT,
    title     TEXT,
    url       TEXT,
    published_at TEXT,
    found_at  TEXT NOT NULL,
    UNIQUE(slug, post_id, target_id)
);
CREATE INDEX IF NOT EXISTS idx_pending_target ON pending(target_id);

CREATE TABLE IF NOT EXISTS deliveries (
    slug      TEXT NOT NULL,
    post_id   TEXT NOT NULL,
    target_id TEXT NOT NULL,
    sent_at   TEXT NOT NULL,
    PRIMARY KEY (slug, post_id, target_id)
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    p = Path(db_path) if db_path else DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def _retry(fn, *args, attempts: int = 5, **kw):
    last = None
    for _ in range(attempts):
        try:
            return fn(*args, **kw)
        except sqlite3.OperationalError as e:  # "database is locked"
            last = e
            time.sleep(0.2)
    raise last  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# subscriptions
# --------------------------------------------------------------------------- #
def add_subscription(conn: sqlite3.Connection, *, user_id: str, slug: str, url: str,
                     filter_prompt: Optional[str], schedule: str,
                     target_kind: str, target_id: str) -> bool:
    """추가(또는 이미 있으면 필터/스케줄 갱신). 새로 생겼으면 True."""
    def _do():
        cur = conn.execute(
            "INSERT INTO subscriptions(user_id,slug,url,filter_prompt,schedule,target_kind,target_id,created_at) "
            "VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(user_id,slug,target_id) DO UPDATE SET filter_prompt=excluded.filter_prompt, schedule=excluded.schedule, url=excluded.url",
            (user_id, slug, url, filter_prompt, schedule, target_kind, target_id, _now_iso()),
        )
        conn.commit()
        return cur.rowcount == 1 and conn.total_changes  # rowcount is unreliable for upsert; treat as ok
    _retry(_do)
    # "새로 생겼나"는 굳이 정확히 안 따짐 — 호출부는 성공/실패만 봄
    return True


def remove_subscription(conn: sqlite3.Connection, *, user_id: str, slug: str) -> int:
    def _do():
        cur = conn.execute("DELETE FROM subscriptions WHERE user_id=? AND slug=?", (user_id, slug))
        conn.commit()
        return cur.rowcount
    return _retry(_do)


def list_subscriptions(conn: sqlite3.Connection, *, user_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM subscriptions WHERE user_id=? ORDER BY created_at", (user_id,)
    ).fetchall()


def subscriptions_for_slug(conn: sqlite3.Connection, slug: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM subscriptions WHERE slug=?", (slug,)).fetchall()


def all_slugs(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT DISTINCT slug FROM subscriptions").fetchall()]


def counts(conn: sqlite3.Connection) -> dict:
    n_subs = conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0]
    n_slugs = conn.execute("SELECT COUNT(DISTINCT slug) FROM subscriptions").fetchone()[0]
    n_pending = conn.execute("SELECT COUNT(*) FROM pending").fetchone()[0]
    n_deliv = conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]
    return {"subscriptions": n_subs, "slugs": n_slugs, "pending": n_pending, "deliveries": n_deliv}


# --------------------------------------------------------------------------- #
# deliveries
# --------------------------------------------------------------------------- #
def was_delivered(conn: sqlite3.Connection, slug: str, post_id: str, target_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM deliveries WHERE slug=? AND post_id=? AND target_id=?",
        (slug, str(post_id), target_id),
    ).fetchone() is not None


def mark_delivered(conn: sqlite3.Connection, slug: str, post_id: str, target_id: str) -> None:
    def _do():
        conn.execute(
            "INSERT OR IGNORE INTO deliveries(slug,post_id,target_id,sent_at) VALUES(?,?,?,?)",
            (slug, str(post_id), target_id, _now_iso()),
        )
        conn.commit()
    _retry(_do)


# --------------------------------------------------------------------------- #
# pending (digest outbox)
# --------------------------------------------------------------------------- #
def add_pending(conn: sqlite3.Connection, *, slug: str, post_id: str, target_id: str,
                summary: Optional[str], title: Optional[str], url: Optional[str],
                published_at: Optional[str]) -> None:
    def _do():
        conn.execute(
            "INSERT OR IGNORE INTO pending(slug,post_id,target_id,summary,title,url,published_at,found_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (slug, str(post_id), target_id, summary, title, url, published_at, _now_iso()),
        )
        conn.commit()
    _retry(_do)


def pending_for_target(conn: sqlite3.Connection, target_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM pending WHERE target_id=? ORDER BY published_at, id", (target_id,)
    ).fetchall()


def pending_target_ids(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT DISTINCT target_id FROM pending").fetchall()]


def drain_pending(conn: sqlite3.Connection, target_id: str) -> list[sqlite3.Row]:
    """그 target 의 pending 을 모두 deliveries 로 옮기고 옮긴 행들을 반환(트랜잭션).

    호출부는 *먼저* 이걸로 행을 받아 메시지를 만들어 발송 시도하는 게 아니라,
    발송에 성공한 뒤 commit 하는 패턴을 권장 — 그래서 여기선 행만 SELECT 해서 주고,
    실제 이동은 mark_drained() 로 따로 한다. (발송 실패 시 pending 유지)
    """
    return pending_for_target(conn, target_id)


def mark_drained(conn: sqlite3.Connection, target_id: str, rows: list[sqlite3.Row]) -> None:
    def _do():
        for r in rows:
            conn.execute(
                "INSERT OR IGNORE INTO deliveries(slug,post_id,target_id,sent_at) VALUES(?,?,?,?)",
                (r["slug"], r["post_id"], target_id, _now_iso()),
            )
            conn.execute("DELETE FROM pending WHERE id=?", (r["id"],))
        conn.commit()
    _retry(_do)
