"""SQLite — 봇 구독 정보 + 발송 기록 + register/re-probe 잡 큐.

DB 파일: output/bot.sqlite3 (이미 .gitignore 됨).
필터 프롬프트·발송 대상·스케줄은 *여기에만* 산다 (configs/ · poll_state/ 엔 절대 안 씀).

테이블:
  subscriptions(user_id, slug, url, filter_prompt, schedule, target_kind, target_id, notify_empty, created_at)
      schedule = 'realtime' (전 행 고정). 폴링 직후 notify.py 가 즉시 발송. 사용자 시각 선택 옵션 없음.
                 컬럼은 유지 — _migrate 가 HH:MM/그 외 값을 일괄 'realtime' 으로 강제 변환(idempotent).
      target_kind = 'dm' (target_id = user_id) | 'channel' (target_id = channel_id)
      notify_empty = 1 이면 폴링 결과 새 글이 없어도 "새 공지 없음" 한 줄을 보냄 (기본 0).
                 realtime_notify_empty_subs() 가 schedule='realtime' AND notify_empty=1 행을 잡음.
      UNIQUE(user_id, slug, target_id) → /watch 멱등
  pending / digest_sent: 옛 다이제스트(HH:MM) 경로의 잔재 테이블. 현 deployment 에선 비어있고 채워질 일 없음.
      유지하는 이유: 마이그레이션 직후의 pre-migration pending 행 잔류 대비 + 향후 롤백 여지.
  deliveries(slug, post_id, target_id, sent_at)          이미 보낸 (slug,post_id,target_id) — 다시 안 보냄
      PRIMARY KEY(slug, post_id, target_id)
  jobs(id, kind, url, slug, article_url, via, requested_by, ack_*, sub_payload, status, ...)
      register/re-probe 잡 큐. bot/worker.py 가 직렬로 처리(chromium 단일 직렬). FIFO by id.
      kind = 'register' (사용자 /watch·/preview) | 'reprobe' (poll.py 의 깨짐 감지)
      status = 'pending' → 'running' → 'done' | 'failed'
  reports(id, user_id, username, slug, issue, created_at, status, resolved_at, resolved_note)
      사용자 `/report` 가 쌓는 신고. open → resolved. bot/inspector.py 의 진단 + admin 명령에서 사용.
  announce_prefs(scope_kind, scope_id, opted_out, updated_at)
      공지 옵트아웃 설정. scope_kind='dm' → scope_id=user_id, 'channel' → scope_id=channel_id.
      기본 opt-in — *row 가 있고 opted_out=1* 인 경우만 발송 대상에서 제외 (행 없음 = 수신).
  announcements(id, title, message, sent_by, sent_at, dm_sent, dm_failed, channel_sent, channel_failed)
      `/admin announce` 발송 audit. 재발송 dedup 안 함 — owner 가 같은 글 재전송 가능.
  feedback(id, user_id, username, message, created_at)
      `/feedback` 으로 사용자가 보낸 자유 의견. status 없음(inbox-only).
      slug/triage 무관 — owner 가 읽고 자체 판단.
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

-- 다이제스트 KST 일자별 발송 cap (target_id, schedule HH:MM, kst_date) — 레거시(HH:MM) 경로 전용.
-- 현 deployment 의 realtime 구독은 cap 을 기록하지 않음(_immediate_ 묶음 분기). 테이블 사실상 영구 빈 상태.
CREATE TABLE IF NOT EXISTS digest_sent (
    target_id TEXT NOT NULL,
    schedule  TEXT NOT NULL,
    kst_date  TEXT NOT NULL,
    sent_at   TEXT NOT NULL,
    PRIMARY KEY (target_id, schedule, kst_date)
);

-- 사용자 문제 신고 (`/report`). owner 가 진단·해결. status='open' 인 행이 admin triage 대상.
-- resolved_at·resolved_note 는 `/admin resolve` 가 채움. username 은 신고 시점 스냅샷(추후 닉네임
-- 변경에도 누가 신고했는지 추적 가능).
CREATE TABLE IF NOT EXISTS reports (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        TEXT NOT NULL,
    username       TEXT,
    slug           TEXT NOT NULL,
    issue          TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'open'
                   CHECK (status IN ('open','resolved')),
    resolved_at    TEXT,
    resolved_note  TEXT
);
CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status, id);
CREATE INDEX IF NOT EXISTS idx_reports_slug ON reports(slug);

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
    result_tail     TEXT,
    attempts        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, id);
CREATE INDEX IF NOT EXISTS idx_jobs_slug ON jobs(slug);

-- 공지 옵트아웃: 기본 opt-in. 행이 있고 opted_out=1 일 때만 발송에서 제외.
-- scope_kind='dm' → scope_id 는 discord user_id, 'channel' → channel_id.
-- 옵트인 복귀는 opted_out=0 으로 set (행 유지 — updated_at 추적용).
CREATE TABLE IF NOT EXISTS announce_prefs (
    scope_kind TEXT NOT NULL CHECK (scope_kind IN ('dm','channel')),
    scope_id   TEXT NOT NULL,
    opted_out  INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (scope_kind, scope_id)
);

-- 공지 발송 audit. 같은 글 재전송 dedup 안 함 — 운영자 의도된 재전송 허용.
-- recipient_targets: scoped announce 만 채움 — JSON `[[kind,id], ...]`. NULL = full broadcast(legacy `/admin announce`).
CREATE TABLE IF NOT EXISTS announcements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    message         TEXT NOT NULL,
    sent_by         TEXT NOT NULL,
    sent_at         TEXT NOT NULL,
    dm_sent         INTEGER NOT NULL DEFAULT 0,
    dm_failed       INTEGER NOT NULL DEFAULT 0,
    channel_sent    INTEGER NOT NULL DEFAULT 0,
    channel_failed  INTEGER NOT NULL DEFAULT 0,
    recipient_targets TEXT
);
CREATE INDEX IF NOT EXISTS idx_announce_sent_at ON announcements(sent_at DESC);
-- deliveries 의 target 기준 조회/삭제(scoped replay 용) 가속.
CREATE INDEX IF NOT EXISTS idx_deliveries_target ON deliveries(target_id, slug);

-- 자유 의견(`/feedback`). slug/status 없음 — owner 가 읽기만. message 는 5900자 cap(클라이언트 강제).
CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT NOT NULL,
    username   TEXT,
    message    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at DESC);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _migrate(conn: sqlite3.Connection) -> None:
    """이미 존재하는 옛 DB 에 빠진 컬럼 추가 (SQLite 는 ADD COLUMN IF NOT EXISTS 가 없음)."""
    sub_cols = {r[1] for r in conn.execute("PRAGMA table_info(subscriptions)").fetchall()}
    if "notify_empty" not in sub_cols:
        conn.execute("ALTER TABLE subscriptions ADD COLUMN notify_empty INTEGER NOT NULL DEFAULT 0")
    # 모든 구독은 polling 직후 즉시 발송(realtime). 옛 HH:MM schedule 행도 일괄 이전 — idempotent.
    conn.execute("UPDATE subscriptions SET schedule='realtime' WHERE schedule!='realtime'")
    # scoped announce 용 recipient_targets 컬럼 (옛 DB 에 추가).
    ann_cols = {r[1] for r in conn.execute("PRAGMA table_info(announcements)").fetchall()}
    if "recipient_targets" not in ann_cols:
        conn.execute("ALTER TABLE announcements ADD COLUMN recipient_targets TEXT")
    # deliveries 의 target_id 기준 lookup/삭제 인덱스 (옛 DB 에 추가).
    conn.execute("CREATE INDEX IF NOT EXISTS idx_deliveries_target ON deliveries(target_id, slug)")
    # 봇 재시작으로 인한 잡 재실행 횟수 추적 (옛 DB 에 추가).
    # reset_running_to_pending 이 running 잡을 pending 으로 되돌릴 때마다 +1.
    # worker 는 attempts>0 인 잡 시작 시 ack 에 재시작 안내 메시지를 띄움.
    # ALTER TABLE 자체는 두 프로세스가 동시에 PRAGMA 후 ALTER 하면 "duplicate column" 으로 한쪽이
    # 죽을 수 있어 — N100 단일 봇이라 실제 race 거의 없지만, 방어적으로 OperationalError swallow.
    jobs_cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    if "attempts" not in jobs_cols:
        try:
            conn.execute("ALTER TABLE jobs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise
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


def deliveries_for_target(conn: sqlite3.Connection, target_id: str, *,
                          slug: Optional[str] = None, limit: int = 50) -> list[sqlite3.Row]:
    """user×slug detail 의 발송 이력 표시·재발송 후보 list."""
    if slug is None:
        return conn.execute(
            "SELECT slug, post_id, target_id, sent_at FROM deliveries "
            "WHERE target_id=? ORDER BY sent_at DESC LIMIT ?",
            (target_id, limit),
        ).fetchall()
    return conn.execute(
        "SELECT slug, post_id, target_id, sent_at FROM deliveries "
        "WHERE target_id=? AND slug=? ORDER BY sent_at DESC LIMIT ?",
        (target_id, slug, limit),
    ).fetchall()


def deliveries_count_for_target(conn: sqlite3.Connection, target_id: str) -> int:
    return int(conn.execute(
        "SELECT COUNT(*) FROM deliveries WHERE target_id=?", (target_id,)
    ).fetchone()[0])


def delete_delivery(conn: sqlite3.Connection, *, slug: str, post_id: str, target_id: str) -> int:
    """M2 — (slug, post_id, target_id) 한 행 삭제. 반환 = 삭제된 row 수 (0 또는 1)."""
    def _do():
        cur = conn.execute(
            "DELETE FROM deliveries WHERE slug=? AND post_id=? AND target_id=?",
            (slug, str(post_id), target_id),
        )
        conn.commit()
        return cur.rowcount
    return _retry(_do)


def delete_deliveries_for_target(conn: sqlite3.Connection, *, slug: str, target_id: str) -> int:
    """M3 — (slug, target_id) 의 모든 deliveries 삭제. 반환 = 삭제된 row 수."""
    def _do():
        cur = conn.execute(
            "DELETE FROM deliveries WHERE slug=? AND target_id=?",
            (slug, target_id),
        )
        conn.commit()
        return cur.rowcount
    return _retry(_do)


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


def count_user_register_jobs_since(conn: sqlite3.Connection, user_id: str, since_iso: str) -> int:
    """rate-limit 용 — 특정 user_id 가 since_iso 이후 enqueue 한 register 잡 수.
    `requested_by` 는 JSON {"id":..., "name":...} — `json_extract($.id)` 로 안전 매칭 (substring 매칭 X)."""
    return int(conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE kind='register' "
        "AND json_extract(requested_by, '$.id')=? AND created_at >= ?",
        (str(user_id), since_iso),
    ).fetchone()[0])


def reset_running_to_pending(conn: sqlite3.Connection) -> int:
    """봇 재시작 직후 호출 — 이전 worker 가 들고 있던 running 잡들을 pending 으로 되돌림.
    attempts 컬럼 +1 — worker 가 다음 처리 시작 시 사용자 향 재시작 안내를 띄우는 트리거."""
    def _do():
        cur = conn.execute(
            "UPDATE jobs SET status='pending', started_at=NULL, attempts=attempts+1 "
            "WHERE status='running'"
        )
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


def recent_register_jobs(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    """사용자 `/watch`·`/preview` 가 만든 잡만(=kind='register') 최신 순. inspector.recent_jobs 가 호출."""
    return conn.execute(
        "SELECT * FROM jobs WHERE kind='register' ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()


# --------------------------------------------------------------------------- #
# reports (`/report`) — open/resolved 만 사용. admin triage 와 inspector.diagnose 가 enrich.
# --------------------------------------------------------------------------- #
def add_report(conn: sqlite3.Connection, *, user_id: str, username: Optional[str],
               slug: str, issue: str) -> int:
    def _do():
        cur = conn.execute(
            "INSERT INTO reports(user_id,username,slug,issue,created_at,status) "
            "VALUES(?,?,?,?,?, 'open')",
            (user_id, username, slug, issue, _now_iso()),
        )
        conn.commit()
        return int(cur.lastrowid)
    return _retry(_do)


def list_reports(conn: sqlite3.Connection, *, status: Optional[str] = "open",
                 limit: int = 50) -> list[sqlite3.Row]:
    """status=None 이면 전체. 기본 open 만 최신순."""
    if status is None:
        return conn.execute(
            "SELECT * FROM reports ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return conn.execute(
        "SELECT * FROM reports WHERE status=? ORDER BY id DESC LIMIT ?", (status, limit),
    ).fetchall()


def get_report(conn: sqlite3.Connection, report_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()


def resolve_report(conn: sqlite3.Connection, report_id: int, note: Optional[str]) -> bool:
    def _do():
        cur = conn.execute(
            "UPDATE reports SET status='resolved', resolved_at=?, resolved_note=? "
            "WHERE id=? AND status='open'",
            (_now_iso(), note, report_id),
        )
        conn.commit()
        return cur.rowcount > 0
    return _retry(_do)


# --------------------------------------------------------------------------- #
# announce_prefs — 공지 옵트아웃 토글. 기본 opt-in (행 없음 = 수신).
# --------------------------------------------------------------------------- #
def get_announce_optout(conn: sqlite3.Connection, scope_kind: str, scope_id: str) -> bool:
    if scope_kind not in ("dm", "channel"):
        raise ValueError(f"invalid scope_kind: {scope_kind}")
    row = conn.execute(
        "SELECT opted_out FROM announce_prefs WHERE scope_kind=? AND scope_id=?",
        (scope_kind, scope_id),
    ).fetchone()
    return bool(row["opted_out"]) if row else False


def set_announce_optout(conn: sqlite3.Connection, scope_kind: str, scope_id: str,
                        opted_out: bool) -> None:
    if scope_kind not in ("dm", "channel"):
        raise ValueError(f"invalid scope_kind: {scope_kind}")
    def _do():
        conn.execute(
            "INSERT INTO announce_prefs(scope_kind,scope_id,opted_out,updated_at) "
            "VALUES(?,?,?,?) "
            "ON CONFLICT(scope_kind,scope_id) DO UPDATE SET "
            "opted_out=excluded.opted_out, updated_at=excluded.updated_at",
            (scope_kind, scope_id, 1 if opted_out else 0, _now_iso()),
        )
        conn.commit()
    _retry(_do)


def announce_recipients_dm(conn: sqlite3.Connection) -> list[str]:
    """공지 받을 user_id 목록 — subscriptions 의 distinct user_id, 옵트아웃한 user 제외.
    구독 한 번이라도 한 사람이 대상. 옵트인 default → announce_prefs.opted_out=1 만 제외."""
    rows = conn.execute(
        "SELECT DISTINCT s.user_id FROM subscriptions s "
        "LEFT JOIN announce_prefs p "
        "  ON p.scope_kind='dm' AND p.scope_id=s.user_id "
        "WHERE COALESCE(p.opted_out, 0)=0"
    ).fetchall()
    return [r[0] for r in rows]


def announce_recipients_channel(conn: sqlite3.Connection) -> list[str]:
    """공지 보낼 channel_id 목록 — `/watch here` 로 등록된 distinct channel_id, 옵트아웃 채널 제외."""
    rows = conn.execute(
        "SELECT DISTINCT s.target_id FROM subscriptions s "
        "LEFT JOIN announce_prefs p "
        "  ON p.scope_kind='channel' AND p.scope_id=s.target_id "
        "WHERE s.target_kind='channel' AND COALESCE(p.opted_out, 0)=0"
    ).fetchall()
    return [r[0] for r in rows]


# --------------------------------------------------------------------------- #
# announcements — 발송 audit.
# --------------------------------------------------------------------------- #
def add_announcement(conn: sqlite3.Connection, *, title: str, message: str,
                     sent_by: str, recipient_targets: Optional[str] = None) -> int:
    """`recipient_targets` = JSON `[[kind,id], ...]` 문자열 또는 None(=broadcast)."""
    def _do():
        cur = conn.execute(
            "INSERT INTO announcements(title,message,sent_by,sent_at,recipient_targets) "
            "VALUES(?,?,?,?,?)",
            (title, message, sent_by, _now_iso(), recipient_targets),
        )
        conn.commit()
        return int(cur.lastrowid)
    return _retry(_do)


def update_announcement_counts(conn: sqlite3.Connection, announcement_id: int, *,
                               dm_sent: int, dm_failed: int,
                               channel_sent: int, channel_failed: int) -> None:
    def _do():
        conn.execute(
            "UPDATE announcements SET dm_sent=?, dm_failed=?, channel_sent=?, channel_failed=? "
            "WHERE id=?",
            (dm_sent, dm_failed, channel_sent, channel_failed, announcement_id),
        )
        conn.commit()
    _retry(_do)


def recent_announcements(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM announcements ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()


# --------------------------------------------------------------------------- #
# feedback (`/feedback`) — 의견 inbox. owner 가 `/admin feedback` 으로 읽음.
# --------------------------------------------------------------------------- #
def add_feedback(conn: sqlite3.Connection, *, user_id: str, username: Optional[str],
                 message: str) -> int:
    def _do():
        cur = conn.execute(
            "INSERT INTO feedback(user_id,username,message,created_at) VALUES(?,?,?,?)",
            (user_id, username, message, _now_iso()),
        )
        conn.commit()
        return int(cur.lastrowid)
    return _retry(_do)


def list_feedback(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM feedback ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()


def feedback_for_user(conn: sqlite3.Connection, user_id: str,
                      limit: int = 50) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM feedback WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()


def reports_for_user(conn: sqlite3.Connection, user_id: str,
                     limit: int = 50) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM reports WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()


def jobs_for_user(conn: sqlite3.Connection, user_id: str,
                  limit: int = 50) -> list[sqlite3.Row]:
    """jobs.requested_by JSON 의 `$.id` 가 user_id 인 것. `json_extract` 로 NULL safe.

    requested_by 는 `bot/main.py` 가 `{"id": "...", "name": "..."}` JSON 으로 저장 — `poll-reprobe`
    잡 같은 시스템 enqueue 는 NULL → 이 쿼리에서 자동 제외 (json_extract NULL = NULL → 비교 false).
    """
    return conn.execute(
        "SELECT * FROM jobs WHERE json_extract(requested_by, '$.id')=? "
        "ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()


# --------------------------------------------------------------------------- #
# /users 페이지 — person-entity 집계
# --------------------------------------------------------------------------- #
def list_users(conn: sqlite3.Connection) -> list[dict]:
    """user_id 별 집계 1행. set = subscriptions ∪ feedback ∪ reports ∪ jobs.requested_by.id.

    username = 가장 최근 (feedback / reports / jobs) 중 latest non-null. 없으면 None.
    last_active = MAX(created_at) across subscriptions/feedback/reports/jobs.
    sources = ['watch','feedback','report','job'] 중 그 user 가 해당하는 set.

    페이지네이션·필터는 dashboard 단에서 메모리상으로 — 사용자 수가 작아(수십~수백) 풀스캔 OK.
    """
    # 우선 distinct user_id 집합 + 그 user 가 어떤 source 에 있었는지 표시.
    rows = conn.execute(
        """
        WITH u AS (
            SELECT user_id, 'watch' AS src, created_at FROM subscriptions
            UNION ALL
            SELECT user_id, 'feedback' AS src, created_at FROM feedback
            UNION ALL
            SELECT user_id, 'report' AS src, created_at FROM reports
            UNION ALL
            SELECT json_extract(requested_by, '$.id') AS user_id, 'job' AS src, created_at
              FROM jobs
             WHERE requested_by IS NOT NULL
               AND json_extract(requested_by, '$.id') IS NOT NULL
        )
        SELECT user_id,
               GROUP_CONCAT(DISTINCT src) AS sources,
               MIN(created_at)            AS first_seen,
               MAX(created_at)            AS last_active
          FROM u
         WHERE user_id IS NOT NULL AND user_id != ''
         GROUP BY user_id
        """
    ).fetchall()
    # subscription counts (DM / channel 분리)
    sub_counts = {}
    for r in conn.execute(
        "SELECT user_id, "
        "       SUM(CASE WHEN target_kind='dm' THEN 1 ELSE 0 END)      AS dm,"
        "       SUM(CASE WHEN target_kind='channel' THEN 1 ELSE 0 END) AS ch "
        "FROM subscriptions GROUP BY user_id"
    ).fetchall():
        sub_counts[r["user_id"]] = (int(r["dm"] or 0), int(r["ch"] or 0))
    # feedback / reports counts
    fb_counts = {r["user_id"]: int(r["n"]) for r in conn.execute(
        "SELECT user_id, COUNT(*) AS n FROM feedback GROUP BY user_id"
    ).fetchall()}
    rep_total = {r["user_id"]: int(r["n"]) for r in conn.execute(
        "SELECT user_id, COUNT(*) AS n FROM reports GROUP BY user_id"
    ).fetchall()}
    rep_open = {r["user_id"]: int(r["n"]) for r in conn.execute(
        "SELECT user_id, COUNT(*) AS n FROM reports WHERE status='open' GROUP BY user_id"
    ).fetchall()}
    # username = 가장 최근 (feedback/reports/jobs) 의 비어있지 않은 값
    names: dict[str, str] = {}
    for r in conn.execute(
        "SELECT user_id, username FROM feedback "
        "WHERE username IS NOT NULL AND username != '' ORDER BY id DESC"
    ).fetchall():
        names.setdefault(r["user_id"], r["username"])
    for r in conn.execute(
        "SELECT user_id, username FROM reports "
        "WHERE username IS NOT NULL AND username != '' ORDER BY id DESC"
    ).fetchall():
        names.setdefault(r["user_id"], r["username"])
    for r in conn.execute(
        "SELECT json_extract(requested_by, '$.id') AS uid, "
        "       json_extract(requested_by, '$.name') AS uname "
        "FROM jobs WHERE requested_by IS NOT NULL ORDER BY id DESC"
    ).fetchall():
        if r["uid"] and r["uname"]:
            names.setdefault(r["uid"], r["uname"])

    # deliveries: target_id 가 DM 이면 user_id 와 같음 → user 별 deliveries 합산.
    # DM target_id 는 user_id 와 동일하므로 deliveries.target_id ∈ user set 인 행만 카운트.
    deliv_count: dict[str, int] = {}
    deliv_last: dict[str, str] = {}
    for r in conn.execute(
        "SELECT target_id, COUNT(*) AS n, MAX(sent_at) AS last_sent "
        "FROM deliveries GROUP BY target_id"
    ).fetchall():
        deliv_count[r["target_id"]] = int(r["n"])
        deliv_last[r["target_id"]] = r["last_sent"]

    out: list[dict] = []
    for r in rows:
        uid = r["user_id"]
        dm, ch = sub_counts.get(uid, (0, 0))
        out.append({
            "user_id":          uid,
            "username":         names.get(uid),
            "sources":          sorted((r["sources"] or "").split(",")) if r["sources"] else [],
            "n_dm_subs":        dm,
            "n_channel_subs":   ch,
            "n_subs":           dm + ch,
            "n_feedback":       fb_counts.get(uid, 0),
            "n_reports_open":   rep_open.get(uid, 0),
            "n_reports_total":  rep_total.get(uid, 0),
            "first_seen":       r["first_seen"],
            "last_active":      r["last_active"],
            "total_deliveries": deliv_count.get(uid, 0),
            "last_delivery_at": deliv_last.get(uid),
        })
    return out


def get_user(conn: sqlite3.Connection, user_id: str) -> Optional[dict]:
    """단일 user 상세 — None 이면 그 user_id 는 set 에 없음."""
    summary = next((u for u in list_users(conn) if u["user_id"] == user_id), None)
    if summary is None:
        return None
    summary["subscriptions"] = [dict(r) for r in conn.execute(
        "SELECT * FROM subscriptions WHERE user_id=? ORDER BY target_kind, created_at",
        (user_id,),
    ).fetchall()]
    summary["feedback"] = [dict(r) for r in feedback_for_user(conn, user_id)]
    summary["reports"] = [dict(r) for r in reports_for_user(conn, user_id)]
    summary["jobs"] = [dict(r) for r in jobs_for_user(conn, user_id)]
    # 최근 deliveries — DM target_id 만 (= user_id). channel 발송은 user 단위로 의미 X.
    summary["recent_deliveries"] = [dict(r) for r in deliveries_for_target(
        conn, user_id, limit=50)]
    return summary
