"""SQLite — 봇 구독 정보 + 다이제스트 대기열 + 발송 기록 + register/re-probe 잡 큐.

DB 파일: output/bot.sqlite3 (이미 .gitignore 됨).
필터 프롬프트·발송 대상·스케줄은 *여기에만* 산다 (configs/ · poll_state/ 엔 절대 안 씀).

테이블:
  subscriptions(user_id, slug, url, filter_prompt, schedule, target_kind, target_id, notify_empty, created_at)
      schedule = 'HH:MM' (KST, 그 시각 폴링 때 묶어 발송). 사용자 선택 옵션은 봇 /watch 에서 제거됨 →
                 신규는 모두 서버 폴링 시각(08:20)으로 저장. 옛 'realtime' 행은 _migrate 가 08:20 으로 변환.
                 컬럼 자체는 유지 — notify.py 의 flush_digests 가 HH:MM 매칭으로 그대로 동작.
      target_kind = 'dm' (target_id = user_id) | 'channel' (target_id = channel_id)
      notify_empty = 1 이면 폴링 결과 새 글이 없어도 "새 공지 없음" 한 줄을 보냄 (기본 0).
                 ⚠ notify.py 의 현 구현은 realtime_notify_empty_subs() 가 schedule='realtime' 만 잡으므로
                 다이제스트 모드에선 실제로 발송 안 됨 — notify.py 수정 시점에 함께 정리 예정.
      UNIQUE(user_id, slug, target_id) → /watch 멱등
  pending(slug, post_id, target_id, summary, found_at)   다이제스트 구독자용 outbox (필터 통과+요약 완료, 아직 미발송)
      UNIQUE(slug, post_id, target_id)
  deliveries(slug, post_id, target_id, sent_at)          이미 보낸 (slug,post_id,target_id) — 다시 안 보냄
      PRIMARY KEY(slug, post_id, target_id)
  jobs(id, kind, url, slug, article_url, via, requested_by, ack_*, sub_payload, status, ...)
      register/re-probe 잡 큐. bot/worker.py 가 직렬로 처리(chromium 단일 직렬). FIFO by id.
      kind = 'register' (사용자 /watch·/preview) | 'reprobe' (poll.py 의 깨짐 감지)
      status = 'pending' → 'running' → 'done' | 'failed'
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
    notify_empty INTEGER NOT NULL DEFAULT 0,
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

-- 다이제스트 KST 일자별 발송 cap (target_id, schedule HH:MM, kst_date).
-- flush_digests 가 그 일자에 이미 비웠으면 같은 timer 슬롯이 또 비우지 못하게 막음.
-- 24×/일 폴링 시에도 schedule 시각에 1회만 다이제스트 발송됨.
CREATE TABLE IF NOT EXISTS digest_sent (
    target_id TEXT NOT NULL,
    schedule  TEXT NOT NULL,
    kst_date  TEXT NOT NULL,
    sent_at   TEXT NOT NULL,
    PRIMARY KEY (target_id, schedule, kst_date)
);

CREATE TABLE IF NOT EXISTS jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT NOT NULL CHECK (kind IN ('register','reprobe')),
    url             TEXT NOT NULL,
    slug            TEXT NOT NULL,
    article_url     TEXT,
    via             TEXT,
    requested_by    TEXT,
    ack_channel_id  TEXT,
    ack_message_id  TEXT,
    sub_payload     TEXT,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','running','done','failed')),
    created_at      TEXT NOT NULL,
    started_at      TEXT,
    finished_at     TEXT,
    result_rc       INTEGER,
    result_tail     TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, id);
CREATE INDEX IF NOT EXISTS idx_jobs_slug ON jobs(slug);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _migrate(conn: sqlite3.Connection) -> None:
    """이미 존재하는 옛 DB 에 빠진 컬럼 추가 (SQLite 는 ADD COLUMN IF NOT EXISTS 가 없음)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(subscriptions)").fetchall()}
    if "notify_empty" not in cols:
        conn.execute("ALTER TABLE subscriptions ADD COLUMN notify_empty INTEGER NOT NULL DEFAULT 0")
    # /watch 에서 사용자 시간 선택 옵션을 제거하면서 schedule='realtime' 신규 생성은 끊김.
    # 기존 realtime 구독은 서버 폴링 시각(08:20 KST)으로 일괄 이전 — idempotent.
    conn.execute("UPDATE subscriptions SET schedule='08:20' WHERE schedule='realtime'")
    conn.commit()


def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    p = Path(db_path) if db_path else DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    conn.commit()
    _migrate(conn)
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
                     target_kind: str, target_id: str, notify_empty: bool = False) -> bool:
    """추가(또는 이미 있으면 필터/스케줄/notify_empty 갱신). 새로 생겼으면 True."""
    def _do():
        cur = conn.execute(
            "INSERT INTO subscriptions(user_id,slug,url,filter_prompt,schedule,target_kind,target_id,notify_empty,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(user_id,slug,target_id) DO UPDATE SET "
            "filter_prompt=excluded.filter_prompt, schedule=excluded.schedule, url=excluded.url, notify_empty=excluded.notify_empty",
            (user_id, slug, url, filter_prompt, schedule, target_kind, target_id, 1 if notify_empty else 0, _now_iso()),
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


def realtime_notify_empty_subs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """notify_empty=1 인 realtime 구독들 (폴링 후 '새 공지 없음' 한 줄 받을 대상)."""
    return conn.execute(
        "SELECT * FROM subscriptions WHERE notify_empty=1 AND schedule='realtime'"
    ).fetchall()


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


# --------------------------------------------------------------------------- #
# digest_sent (KST 일자별 다이제스트 발송 cap)
# --------------------------------------------------------------------------- #
def digest_was_sent(conn: sqlite3.Connection, target_id: str, schedule: str, kst_date: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM digest_sent WHERE target_id=? AND schedule=? AND kst_date=?",
        (target_id, schedule, kst_date),
    ).fetchone() is not None


def mark_digest_sent(conn: sqlite3.Connection, target_id: str, schedule: str, kst_date: str) -> None:
    def _do():
        conn.execute(
            "INSERT OR IGNORE INTO digest_sent(target_id,schedule,kst_date,sent_at) VALUES(?,?,?,?)",
            (target_id, schedule, kst_date, _now_iso()),
        )
        conn.commit()
    _retry(_do)


# --------------------------------------------------------------------------- #
# jobs (register / re-probe 큐) — bot/worker.py 가 소비
# --------------------------------------------------------------------------- #
def enqueue_job(conn: sqlite3.Connection, *,
                kind: str, url: str, slug: str,
                article_url: Optional[str] = None,
                via: Optional[str] = None,
                requested_by: Optional[str] = None,
                ack_channel_id: Optional[str] = None,
                ack_message_id: Optional[str] = None,
                sub_payload: Optional[str] = None,
                dedupe: bool = True) -> tuple[int, bool]:
    """잡 enqueue. (job_id, newly_inserted) 반환.

    dedupe=True 면 같은 (kind, slug) 가 이미 pending/running 이면 그 잡 id 를 반환하고 새로 안 넣음.
    request_by/sub_payload 는 JSON 문자열. ack_* 는 호출자가 보낸 채널 메시지 id (worker 가 그걸 edit).
    """
    if kind not in ("register", "reprobe"):
        raise ValueError(f"invalid kind: {kind}")
    if dedupe:
        row = conn.execute(
            "SELECT id FROM jobs WHERE kind=? AND slug=? AND status IN ('pending','running') ORDER BY id ASC LIMIT 1",
            (kind, slug),
        ).fetchone()
        if row is not None:
            return int(row["id"]), False
    def _do():
        cur = conn.execute(
            "INSERT INTO jobs(kind,url,slug,article_url,via,requested_by,ack_channel_id,ack_message_id,sub_payload,"
            "status,created_at) VALUES(?,?,?,?,?,?,?,?,?, 'pending', ?)",
            (kind, url, slug, article_url, via, requested_by, ack_channel_id, ack_message_id, sub_payload, _now_iso()),
        )
        conn.commit()
        return int(cur.lastrowid)
    return _retry(_do), True


def claim_next_pending(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    """가장 오래된 pending 잡 하나를 running 으로 표시하고 반환. 없으면 None.

    SELECT-then-UPDATE 패턴 (Python sqlite3 의 implicit 트랜잭션과 충돌 없도록 BEGIN IMMEDIATE 피함).
    UPDATE WHERE status='pending' 조건으로 race 가드 — 다른 워커가 같은 잡 채갔으면 rowcount=0, 다음 잡으로.
    """
    for _ in range(8):
        row = conn.execute(
            "SELECT id FROM jobs WHERE status='pending' ORDER BY id ASC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        def _do():
            cur = conn.execute(
                "UPDATE jobs SET status='running', started_at=? WHERE id=? AND status='pending'",
                (_now_iso(), row["id"]),
            )
            conn.commit()
            return cur.rowcount
        if _retry(_do) > 0:
            return conn.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
        # race — 다른 워커가 가져감. 다음 후보 시도
    return None


def mark_job_finished(conn: sqlite3.Connection, job_id: int, *,
                      ok: bool, rc: Optional[int], tail: Optional[str]) -> None:
    """잡을 done/failed 로 표시. status='running' 조건으로 멱등(두 번 불려도 두 번째는 no-op).
    이래서 _process_job 의 try/except finalizer 가 이미 mark 끝낸 잡을 또 fail 로 뒤집지 않음."""
    status = "done" if ok else "failed"
    def _do():
        conn.execute(
            "UPDATE jobs SET status=?, finished_at=?, result_rc=?, result_tail=? "
            "WHERE id=? AND status='running'",
            (status, _now_iso(), rc, (tail or "")[-4000:], job_id),
        )
        conn.commit()
    _retry(_do)


def queue_position(conn: sqlite3.Connection, job_id: int) -> int:
    """이 잡의 큐 위치 (1-base). 이미 running 이면 0, done/failed 면 -1, 없는 잡이면 -1."""
    row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        return -1
    if row["status"] == "running":
        return 0
    if row["status"] in ("done", "failed"):
        return -1
    return int(conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE status='pending' AND id<=?", (job_id,)
    ).fetchone()[0])


def queue_pending_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM jobs WHERE status='pending'").fetchone()[0])


def reset_running_to_pending(conn: sqlite3.Connection) -> int:
    """봇 재시작 직후 호출 — 이전 worker 가 들고 있던 running 잡들을 pending 으로 되돌림."""
    def _do():
        cur = conn.execute("UPDATE jobs SET status='pending', started_at=NULL WHERE status='running'")
        conn.commit()
        return cur.rowcount
    return _retry(_do)


def get_job(conn: sqlite3.Connection, job_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def recent_jobs(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()


def jobs_summary(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "SELECT status, COUNT(*) as n FROM jobs GROUP BY status"
    ).fetchall()
    return {r["status"]: int(r["n"]) for r in rows}
