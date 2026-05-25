"""SQLite — 봇 구독 정보 + 발송 기록 + register/re-probe 잡 큐.

DB 파일: output/bot.sqlite3 (이미 .gitignore 됨).
필터 프롬프트·발송 대상·스케줄은 *여기에만* 산다 (configs/ · poll_state/ 엔 절대 안 씀).

테이블:
  subscriptions(user_id, slug, url, filter_prompt, schedule, target_kind, target_id, notify_empty, created_at)
      schedule = 'realtime' (전 행 고정) — *vestigial*. ADR 0006 이후 발송 시각은 이 컬럼이 아니라
                 user_settings/channel_settings.deliver_at 가 결정 (봇 1분 tick → deliver_due.py).
                 컬럼은 유지 — _migrate 가 옛 HH:MM/그 외 값을 일괄 'realtime' 으로 강제 변환(idempotent).
      target_kind = 'dm' (target_id = user_id) | 'channel' (target_id = channel_id)
      notify_empty = 1 이면 폴링 결과 새 글이 없어도 "새 공지 없음" 한 줄을 보냄 (기본 0).
                 realtime_notify_empty_subs() 가 schedule='realtime' AND notify_empty=1 행을 잡음.
      UNIQUE(user_id, slug, target_id) → /watch 멱등
  pending / digest_sent: 옛 다이제스트(HH:MM) 경로의 잔재 테이블. 현 deployment 에선 비어있고 채워질 일 없음.
      유지하는 이유: 마이그레이션 직후의 pre-migration pending 행 잔류 대비 + 향후 롤백 여지.
  deliveries(slug, post_id, target_id, sent_at)          이미 보낸 (slug,post_id,target_id) — 다시 안 보냄
      PRIMARY KEY(slug, post_id, target_id)
  jobs(id, kind, url, slug, article_url, via, requested_by, ack_*, sub_payload, status, priority, ...)
      register/re-probe 잡 큐 = 우선순위 큐 (priority queue). bot/worker.py 가 pool_size 개로 처리.
      claim(dequeue) 순서 = ORDER BY priority ASC, id ASC (작은 priority 먼저). ADR 0009.
      kind = 'register' (사용자 /watch·/preview) | 'reprobe' (poll.py 의 깨짐 감지)
      priority = enqueue_job 이 via/kind 에서 도출: user(watch/preview)=0 > reprobe=1 > batch-retry(테스트/재시도)=2 > batch(신규 bulk)=3.
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent.parent / "output" / "bot.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS subscriptions (
    id           INTEGER PRIMARY KEY,
    user_id      TEXT NOT NULL,
    slug         TEXT NOT NULL,
    url          TEXT NOT NULL,
    display_title TEXT,
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
    slug           TEXT,
    url            TEXT,
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
    attempts        INTEGER NOT NULL DEFAULT 0,
    priority        INTEGER NOT NULL DEFAULT 0   -- 우선순위 큐 (ADR 0009): 작을수록 먼저 dequeue. enqueue_job 이 via/kind 에서 도출.
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

-- 최근 글 본문 캐시 (ADR 0006). 폴링이 새 글을 raw 로 박음(LLM 0). summary 는 발송창에서
-- 처음 필요할 때 1회 lazy 계산해 채움 → 여러 발송창이 재사용. TTL GC(prune_posts) 로 며칠 후 삭제.
-- forward-only: seen_post_ids 에 없던 새 글만 들어옴 (마이그 이전·lurking 백로그 없음 = 의도).
CREATE TABLE IF NOT EXISTS posts (
    slug         TEXT NOT NULL,
    post_id      TEXT NOT NULL,
    title        TEXT,
    url          TEXT,
    published_at TEXT,
    category     TEXT,
    content_html TEXT,
    summary      TEXT,
    collected_at TEXT NOT NULL,
    PRIMARY KEY (slug, post_id)
);
CREATE INDEX IF NOT EXISTS idx_posts_slug ON posts(slug, collected_at);
CREATE INDEX IF NOT EXISTS idx_posts_collected ON posts(collected_at);

-- per-user 발송 시각 (ADR 0006). DM 수신처. deliver_at = KST 'HH:MM'. 없는 user = 기본 08:30
-- 으로 취급하나, 인덱스 due 쿼리를 위해 /watch·마이그가 행을 seed 한다.
-- last_delivered_date = 마지막 발송한 KST 날짜 (하루 1회 멱등 + 부팅 catch-up 가드).
CREATE TABLE IF NOT EXISTS user_settings (
    user_id             TEXT PRIMARY KEY,
    deliver_at          TEXT NOT NULL DEFAULT '08:30',
    last_delivered_date TEXT,
    updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_user_deliver_at ON user_settings(deliver_at);

-- per-channel 발송 시각 (ADR 0006). 채널 수신처 — 한 채널 = 한 시각 = 한 묶음. Manage-Channel
-- 권한자만 설정. channel_id = subscriptions.target_id (target_kind='channel').
CREATE TABLE IF NOT EXISTS channel_settings (
    channel_id          TEXT PRIMARY KEY,
    deliver_at          TEXT NOT NULL DEFAULT '08:30',
    last_delivered_date TEXT,
    updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_channel_deliver_at ON channel_settings(deliver_at);

-- ADR 0017 — poll/notify runs 추적 + 영속화 검증.
-- 폴링 1회 = 1 row (poll_runs). 사이트 1회 = 1 row (poll_site_runs, finish 시 INSERT).
-- deliver_due 1회 = 1 row (notify_runs). target 1회 = 1 row (notify_target_runs).
-- reaper 가 옛 status='running' row (process 죽음) 를 crashed 로 마킹.
-- helper 는 모두 best-effort — fail 해도 poll/notify 본 흐름 영향 X (§2f).
CREATE TABLE IF NOT EXISTS poll_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_label   TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    reaped_at   TEXT,
    reap_reason TEXT,
    pid         INTEGER NOT NULL,
    host        TEXT,
    git_sha     TEXT,
    args_json   TEXT,
    n_sites     INTEGER,
    n_done      INTEGER NOT NULL DEFAULT 0,
    n_timeout   INTEGER NOT NULL DEFAULT 0,
    n_error     INTEGER NOT NULL DEFAULT 0,
    n_lurking_skipped INTEGER NOT NULL DEFAULT 0,
    n_attempted_unique INTEGER NOT NULL DEFAULT 0,
    n_inserted        INTEGER NOT NULL DEFAULT 0,
    n_present_after   INTEGER NOT NULL DEFAULT 0,
    persist_mismatch_sites INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER,
    status      TEXT NOT NULL DEFAULT 'running'
                CHECK (status IN ('running','done','crashed','killed'))
);
CREATE INDEX IF NOT EXISTS idx_poll_runs_started ON poll_runs(started_at DESC);

CREATE TABLE IF NOT EXISTS poll_site_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES poll_runs(id),
    slug        TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    status      TEXT NOT NULL CHECK (status IN
                ('ok','lurking','breakage','poll_timeout','task_exception',
                 'persist_mismatch','body_empty_drift','reprobe_enqueued',
                 'reprobe_skipped_bug','reprobe_enqueue_failed','run_crashed','error',
                 'chromium_lock_timeout')),
    n_posts            INTEGER NOT NULL DEFAULT 0,
    n_new              INTEGER NOT NULL DEFAULT 0,
    n_attempted_unique INTEGER NOT NULL DEFAULT 0,
    n_inserted         INTEGER NOT NULL DEFAULT 0,
    n_present_after    INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER,
    lock_wait_ms INTEGER,
    error_msg   TEXT,
    note        TEXT,
    UNIQUE(run_id, slug)
);
CREATE INDEX IF NOT EXISTS idx_poll_site_runs_run ON poll_site_runs(run_id, slug);
CREATE INDEX IF NOT EXISTS idx_poll_site_runs_slug ON poll_site_runs(slug, started_at DESC);

CREATE TABLE IF NOT EXISTS notify_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    reaped_at   TEXT,
    reap_reason TEXT,
    pid         INTEGER NOT NULL,
    host        TEXT,
    args_json   TEXT,
    now_hhmm    TEXT,
    today_kst   TEXT,
    n_due_targets    INTEGER NOT NULL DEFAULT 0,
    n_targets_ok     INTEGER NOT NULL DEFAULT 0,
    n_targets_failed INTEGER NOT NULL DEFAULT 0,
    n_posts_delivered INTEGER NOT NULL DEFAULT 0,
    n_empty_notices  INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER,
    status      TEXT NOT NULL DEFAULT 'running'
                CHECK (status IN ('running','done','crashed','killed'))
);
CREATE INDEX IF NOT EXISTS idx_notify_runs_started ON notify_runs(started_at DESC);

CREATE TABLE IF NOT EXISTS notify_target_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES notify_runs(id),
    target_kind TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    status      TEXT NOT NULL CHECK (status IN
                ('ok','empty','no_subs','failed','exception','run_crashed','skipped_test_target')),
    n_posts     INTEGER NOT NULL DEFAULT 0,
    n_chunks    INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER,
    error_msg   TEXT,
    UNIQUE(run_id, target_kind, target_id)
);
CREATE INDEX IF NOT EXISTS idx_notify_target_runs_run ON notify_target_runs(run_id);
CREATE INDEX IF NOT EXISTS idx_notify_target_runs_target ON notify_target_runs(target_kind, target_id, started_at DESC);
"""

# 발송 시각 미설정 수신처의 기본값 (KST HH:MM). ADR 0006.
DEFAULT_DELIVER_AT = "08:30"
KST = timezone(timedelta(hours=9))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _migrate(conn: sqlite3.Connection) -> None:
    """이미 존재하는 옛 DB 에 빠진 컬럼 추가 (SQLite 는 ADD COLUMN IF NOT EXISTS 가 없음)."""
    sub_cols = {r[1] for r in conn.execute("PRAGMA table_info(subscriptions)").fetchall()}
    if "notify_empty" not in sub_cols:
        conn.execute("ALTER TABLE subscriptions ADD COLUMN notify_empty INTEGER NOT NULL DEFAULT 0")
    if "display_title" not in sub_cols:
        conn.execute("ALTER TABLE subscriptions ADD COLUMN display_title TEXT")
    rep_cols = {r[1] for r in conn.execute("PRAGMA table_info(reports)").fetchall()}
    if "url" not in rep_cols:
        conn.execute("ALTER TABLE reports ADD COLUMN url TEXT")
    rep_info = conn.execute("PRAGMA table_info(reports)").fetchall()
    slug_info = next((r for r in rep_info if r[1] == "slug"), None)
    if slug_info is not None and int(slug_info[3]) != 0:
        conn.execute("ALTER TABLE reports RENAME TO reports_old")
        conn.execute("""
            CREATE TABLE reports (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id        TEXT NOT NULL,
                username       TEXT,
                slug           TEXT,
                url            TEXT,
                issue          TEXT NOT NULL,
                created_at     TEXT NOT NULL,
                status         TEXT NOT NULL DEFAULT 'open'
                               CHECK (status IN ('open','resolved')),
                resolved_at    TEXT,
                resolved_note  TEXT
            )
        """)
        conn.execute(
            "INSERT INTO reports(id,user_id,username,slug,url,issue,created_at,status,resolved_at,resolved_note) "
            "SELECT id,user_id,username,slug,url,issue,created_at,status,resolved_at,resolved_note FROM reports_old"
        )
        conn.execute("DROP TABLE reports_old")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status, id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_slug ON reports(slug)")
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
    # 우선순위 큐 (ADR 0009) — 옛 DB 에 priority 컬럼 추가 + 기존 행 backfill.
    # backfill 규칙 = enqueue_job 의 _derive_priority 와 동일 (batch=3 > batch-retry=2 > reprobe=1 > user=0).
    # 컬럼 신규일 때만 backfill — 기존 priority 값(이미 도출됨)을 덮지 않음.
    if "priority" not in jobs_cols:
        try:
            conn.execute("ALTER TABLE jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise
        conn.execute(
            "UPDATE jobs SET priority = CASE "
            "WHEN via='batch' THEN 3 WHEN via='batch-retry' THEN 2 WHEN kind='reprobe' THEN 1 ELSE 0 END"
        )
    # ADR 0006 — 발송 시각 설정 seed. 기존 구독자(DM·채널)에 기본 deliver_at 행을 박아
    # due 쿼리가 인덱스 스캔만으로 동작하게 (행 없음 = default 처리 분기 회피).
    # INSERT OR IGNORE 라 이미 설정한 수신처는 안 건드림. additive — schedule 컬럼은 유지(reader
    # 제거 후 후속 cleanup 마이그에서 DROP). [codex review: 마이그 순서]
    now = _now_iso()
    conn.execute(
        "INSERT OR IGNORE INTO user_settings(user_id, deliver_at, last_delivered_date, updated_at) "
        "SELECT DISTINCT target_id, ?, NULL, ? FROM subscriptions WHERE target_kind='dm'",
        (DEFAULT_DELIVER_AT, now),
    )
    conn.execute(
        "INSERT OR IGNORE INTO channel_settings(channel_id, deliver_at, last_delivered_date, updated_at) "
        "SELECT DISTINCT target_id, ?, NULL, ? FROM subscriptions WHERE target_kind='channel'",
        (DEFAULT_DELIVER_AT, now),
    )
    # ADR 0017 — 옛 enum 으로 만들어진 runs 테이블의 CHECK constraint 마이그.
    # SQLite 의 `CREATE TABLE IF NOT EXISTS` 는 *기존* 테이블의 CHECK 갱신 안 함 → 새 status 값
    # ('error', 'skipped_test_target', 'chromium_lock_timeout') 가 IntegrityError.
    # rebuild 패턴 (new → copy → drop → rename). codex 2차 review HIGH (2026-05-25).
    # ADR 0019 Phase 1 — chromium_lock_timeout 새 status + lock_wait_ms 새 컬럼 추가. probe 통과
    # 시 둘 다 한 번에 rebuild 됨 (rebuild 템플릿이 새 enum + 새 컬럼 둘 다 포함). 옛 'error'
    # probe 는 매우 옛 DB(아직 'error' enum 도 못 받은) 대비 보존.
    _migrate_runs_status_enum(conn, "poll_site_runs", "error",
                              new_create=_POLL_SITE_RUNS_REBUILD)
    _migrate_runs_status_enum(conn, "poll_site_runs", "chromium_lock_timeout",
                              new_create=_POLL_SITE_RUNS_REBUILD)
    _migrate_runs_status_enum(conn, "notify_target_runs", "skipped_test_target",
                              new_create=_NOTIFY_TARGET_RUNS_REBUILD)
    conn.commit()


# ADR 0017 codex 2차 — rebuild 템플릿. _SCHEMA 의 정의와 동기 유지 필수.
_POLL_SITE_RUNS_REBUILD = """
CREATE TABLE poll_site_runs_new (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES poll_runs(id),
    slug        TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    status      TEXT NOT NULL CHECK (status IN
                ('ok','lurking','breakage','poll_timeout','task_exception',
                 'persist_mismatch','body_empty_drift','reprobe_enqueued',
                 'reprobe_skipped_bug','reprobe_enqueue_failed','run_crashed','error',
                 'chromium_lock_timeout')),
    n_posts            INTEGER NOT NULL DEFAULT 0,
    n_new              INTEGER NOT NULL DEFAULT 0,
    n_attempted_unique INTEGER NOT NULL DEFAULT 0,
    n_inserted         INTEGER NOT NULL DEFAULT 0,
    n_present_after    INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER,
    lock_wait_ms INTEGER,
    error_msg   TEXT,
    note        TEXT,
    UNIQUE(run_id, slug)
);
"""

_NOTIFY_TARGET_RUNS_REBUILD = """
CREATE TABLE notify_target_runs_new (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES notify_runs(id),
    target_kind TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    status      TEXT NOT NULL CHECK (status IN
                ('ok','empty','no_subs','failed','exception','run_crashed','skipped_test_target')),
    n_posts     INTEGER NOT NULL DEFAULT 0,
    n_chunks    INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER,
    error_msg   TEXT,
    UNIQUE(run_id, target_kind, target_id)
);
"""


def _migrate_runs_status_enum(conn: sqlite3.Connection, table: str, probe_status: str,
                               *, new_create: str) -> None:
    """ADR 0017 — runs 테이블의 status CHECK 가 새 enum 포함하는지 검사. 없으면 rebuild.

    *probe_status* = 새로 추가된 status 값. sqlite_master 의 CREATE TABLE 텍스트 안에 그 값이
    리터럴로 들어있는지 본다 (단순 substring 검사 — 충분히 보수적). 없으면 rebuild
    (CREATE new → INSERT … SELECT → DROP → RENAME). 테이블 자체 없으면 skip.
    codex 2차 review HIGH (2026-05-25) — `CREATE TABLE IF NOT EXISTS` 가 기존 CHECK 갱신 안 함 봉합.
    """
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone():
        return
    ddl = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    current_sql = ddl[0] if ddl else ""
    if f"'{probe_status}'" in current_sql:
        return  # already migrated
    # foreign key 검사 잠시 끄고 rebuild — REFERENCES 가 새 테이블로 갈아끼우는 도중 reject 막음.
    fk_row = conn.execute("PRAGMA foreign_keys").fetchone()
    fk_state = int(fk_row[0]) if fk_row else 0
    try:
        if fk_state:
            conn.execute("PRAGMA foreign_keys=OFF")
        new_table = f"{table}_new"
        conn.execute(f"DROP TABLE IF EXISTS {new_table}")
        conn.executescript(new_create)
        # 컬럼 명시 복사 — SELECT * 가 컬럼 순서 차이 시 위험.
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        col_list = ",".join(cols)
        conn.execute(f"INSERT INTO {new_table}({col_list}) SELECT {col_list} FROM {table}")
        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {new_table} RENAME TO {table}")
        # 인덱스 재생성 — rebuild 가 옛 인덱스를 같이 drop 함.
        if table == "poll_site_runs":
            conn.execute("CREATE INDEX IF NOT EXISTS idx_poll_site_runs_run ON poll_site_runs(run_id, slug)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_poll_site_runs_slug ON poll_site_runs(slug, started_at DESC)")
        elif table == "notify_target_runs":
            conn.execute("CREATE INDEX IF NOT EXISTS idx_notify_target_runs_run ON notify_target_runs(run_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_notify_target_runs_target ON notify_target_runs(target_kind, target_id, started_at DESC)")
        import sys as _migr_sys
        print(f"[db] migrated {table} status CHECK (added '{probe_status}' enum)", file=_migr_sys.stderr)
    finally:
        if fk_state:
            conn.execute("PRAGMA foreign_keys=ON")


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
                     target_kind: str, target_id: str, notify_empty: bool = False,
                     display_title: Optional[str] = None) -> bool:
    """추가(또는 이미 있으면 필터/스케줄/notify_empty 갱신). 새로 생겼으면 True."""
    def _do():
        cur = conn.execute(
            "INSERT INTO subscriptions(user_id,slug,url,display_title,filter_prompt,schedule,target_kind,target_id,notify_empty,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(user_id,slug,target_id) DO UPDATE SET "
            "filter_prompt=excluded.filter_prompt, schedule=excluded.schedule, url=excluded.url, "
            "display_title=COALESCE(excluded.display_title, subscriptions.display_title), "
            "notify_empty=excluded.notify_empty",
            (user_id, slug, url, display_title, filter_prompt, schedule, target_kind, target_id,
             1 if notify_empty else 0, _now_iso()),
        )
        conn.commit()
        return cur.rowcount == 1 and conn.total_changes  # rowcount is unreliable for upsert; treat as ok
    _retry(_do)
    # "새로 생겼나"는 굳이 정확히 안 따짐 — 호출부는 성공/실패만 봄
    return True


def remove_subscription(conn: sqlite3.Connection, *, user_id: str, slug: str) -> int:
    """slug 의 *모든* 구독 제거 — `/unwatch` 류 URL 단위 일괄 해제용. /list UI 의 단일 행 해제는
    `remove_subscription_by_id` 사용 (같은 slug 의 DM+채널 양쪽 구독 시 한 번에 사라지는 함정 회피)."""
    def _do():
        cur = conn.execute("DELETE FROM subscriptions WHERE user_id=? AND slug=?", (user_id, slug))
        conn.commit()
        return cur.rowcount
    return _retry(_do)


def remove_subscription_by_id(conn: sqlite3.Connection, *, user_id: str, sub_id: int) -> int:
    """단일 row 제거 (id 기준) — /list UI ✕ 버튼이 쓴다. user_id 가드는 본인 row 만 지우게."""
    def _do():
        cur = conn.execute("DELETE FROM subscriptions WHERE user_id=? AND id=?", (user_id, sub_id))
        conn.commit()
        return cur.rowcount
    return _retry(_do)


def list_subscriptions(conn: sqlite3.Connection, *, user_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM subscriptions WHERE user_id=? ORDER BY created_at", (user_id,)
    ).fetchall()


def update_subscription_filter(conn: sqlite3.Connection, *, user_id: str, sub_id: int,
                               filter_prompt: Optional[str]) -> bool:
    """단일 row 의 filter_prompt 갱신 (id 기준). user_id 가드는 본인 row 만."""
    def _do():
        cur = conn.execute(
            "UPDATE subscriptions SET filter_prompt=? WHERE user_id=? AND id=?",
            (filter_prompt, user_id, sub_id),
        )
        conn.commit()
        return cur.rowcount > 0
    return _retry(_do)


def display_title_for_slug(conn: sqlite3.Connection, slug: str) -> Optional[str]:
    row = conn.execute(
        "SELECT display_title FROM subscriptions "
        "WHERE slug=? AND display_title IS NOT NULL AND display_title!='' "
        "ORDER BY created_at DESC LIMIT 1",
        (slug,),
    ).fetchone()
    return row["display_title"] if row else None


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


def subscriptions_for_target(conn: sqlite3.Connection, target_id: str) -> list[sqlite3.Row]:
    """한 수신처(DM user_id 또는 channel_id)의 모든 구독 — 발송창 flush 가 slug·필터·created_at 수집."""
    return conn.execute(
        "SELECT * FROM subscriptions WHERE target_id=? ORDER BY slug", (target_id,)
    ).fetchall()


# --------------------------------------------------------------------------- #
# posts — 최근 글 본문 캐시 (ADR 0006)
# --------------------------------------------------------------------------- #
def upsert_post(conn: sqlite3.Connection, slug: str, post: dict) -> None:
    """폴링이 발견한 새 글을 raw 로 박음 (summary=NULL). 이미 있으면 무시 — 재폴링이 같은 글을
    덮어써 summary 캐시를 날리지 않게 INSERT OR IGNORE."""
    def _do():
        conn.execute(
            "INSERT OR IGNORE INTO posts(slug,post_id,title,url,published_at,category,content_html,summary,collected_at) "
            "VALUES(?,?,?,?,?,?,?,NULL,?)",
            (slug, str(post.get("post_id")), post.get("title"), post.get("url"),
             post.get("published_at"), post.get("category"), post.get("content_html"), _now_iso()),
        )
        conn.commit()
    _retry(_do)


def set_post_summary(conn: sqlite3.Connection, slug: str, post_id: str, summary: str) -> None:
    """발송창에서 lazy 계산한 요약을 캐시 — 이후 다른 발송창이 재사용."""
    def _do():
        conn.execute("UPDATE posts SET summary=? WHERE slug=? AND post_id=?",
                     (summary, slug, str(post_id)))
        conn.commit()
    _retry(_do)


def posts_for_slug_since(conn: sqlite3.Connection, slug: str, since_iso: str) -> list[sqlite3.Row]:
    """slug 의 글 중 collected_at >= since (구독 생성 시점 하한). published_at 오름차순.
    [codex review CRITICAL: created_at 하한으로 신규 구독자 백로그 폭탄 차단]"""
    return conn.execute(
        "SELECT * FROM posts WHERE slug=? AND collected_at>=? ORDER BY published_at, post_id",
        (slug, since_iso),
    ).fetchall()


def prune_posts(conn: sqlite3.Connection, *, keep_days: int = 7) -> int:
    """TTL GC — collected_at 이 keep_days 보다 오래된 글 삭제. 단 아직 그 글을 받지 않은 구독
    대상이 남아 있으면 보존 ([codex review MEDIUM: 미수신 글 삭제 방지]). 반환 = 삭제 row 수."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
    def _do():
        # 미수신 가드: 그 글을 구독하는 target 중 deliveries 에 없는 게 하나라도 있으면 skip.
        cur = conn.execute(
            "DELETE FROM posts WHERE collected_at < ? AND NOT EXISTS ("
            "  SELECT 1 FROM subscriptions s WHERE s.slug = posts.slug "
            "    AND posts.collected_at >= s.created_at "
            "    AND NOT EXISTS (SELECT 1 FROM deliveries d "
            "       WHERE d.slug=posts.slug AND d.post_id=posts.post_id AND d.target_id=s.target_id)"
            ")",
            (cutoff,),
        )
        conn.commit()
        return cur.rowcount
    return _retry(_do)


# --------------------------------------------------------------------------- #
# 발송 시각 설정 (ADR 0006) — user_settings / channel_settings
# --------------------------------------------------------------------------- #
def _settings_meta(target_kind: str) -> tuple[str, str]:
    """(table, id_column) — target_kind 'dm'→user_settings, 'channel'→channel_settings."""
    if target_kind == "dm":
        return "user_settings", "user_id"
    if target_kind == "channel":
        return "channel_settings", "channel_id"
    raise ValueError(f"bad target_kind: {target_kind}")


def ensure_setting(conn: sqlite3.Connection, *, target_kind: str, target_id: str) -> None:
    """수신처 설정 행 보장 (없으면 기본 deliver_at 으로 생성). /watch 가 호출 — due 쿼리가
    인덱스 스캔만으로 동작하게."""
    table, idcol = _settings_meta(target_kind)
    def _do():
        conn.execute(
            f"INSERT OR IGNORE INTO {table}({idcol}, deliver_at, last_delivered_date, updated_at) "
            f"VALUES(?,?,NULL,?)",
            (target_id, DEFAULT_DELIVER_AT, _now_iso()),
        )
        conn.commit()
    _retry(_do)


def get_deliver_at(conn: sqlite3.Connection, *, target_kind: str, target_id: str) -> str:
    """설정된 deliver_at (없으면 DEFAULT_DELIVER_AT)."""
    table, idcol = _settings_meta(target_kind)
    row = conn.execute(f"SELECT deliver_at FROM {table} WHERE {idcol}=?", (target_id,)).fetchone()
    return row["deliver_at"] if row else DEFAULT_DELIVER_AT


def set_deliver_at(conn: sqlite3.Connection, *, target_kind: str, target_id: str, deliver_at: str) -> None:
    """발송 시각 설정/갱신 (HH:MM). 행 없으면 생성."""
    table, idcol = _settings_meta(target_kind)
    def _do():
        conn.execute(
            f"INSERT INTO {table}({idcol}, deliver_at, last_delivered_date, updated_at) "
            f"VALUES(?,?,NULL,?) "
            f"ON CONFLICT({idcol}) DO UPDATE SET deliver_at=excluded.deliver_at, updated_at=excluded.updated_at",
            (target_id, deliver_at, _now_iso()),
        )
        conn.commit()
    _retry(_do)


def due_targets(conn: sqlite3.Connection, *, now_hhmm: str, today_kst: str) -> list[dict]:
    """발송창 도래 + 오늘 아직 안 보낸 수신처 목록. due 조건: deliver_at <= now_hhmm AND
    (last_delivered_date IS NULL OR < today). <= 라 봇이 분을 놓쳐도 다음 tick 이 catch-up.
    반환 [{target_kind, target_id, deliver_at}]. (HH:MM 은 zero-padded 문자열 비교 = 시각 비교)"""
    out: list[dict] = []
    for kind, table, idcol in (("dm", "user_settings", "user_id"),
                               ("channel", "channel_settings", "channel_id")):
        rows = conn.execute(
            f"SELECT {idcol} AS tid, deliver_at FROM {table} "
            f"WHERE deliver_at <= ? AND (last_delivered_date IS NULL OR last_delivered_date < ?)",
            (now_hhmm, today_kst),
        ).fetchall()
        for r in rows:
            out.append({"target_kind": kind, "target_id": r["tid"], "deliver_at": r["deliver_at"]})
    return out


def mark_setting_delivered(conn: sqlite3.Connection, *, target_kind: str, target_id: str,
                           today_kst: str) -> None:
    """발송창 flush 완료 — last_delivered_date 박아 오늘 재발송 차단."""
    table, idcol = _settings_meta(target_kind)
    def _do():
        conn.execute(f"UPDATE {table} SET last_delivered_date=? WHERE {idcol}=?",
                     (today_kst, target_id))
        conn.commit()
    _retry(_do)


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
def _derive_priority(kind: str, via: Optional[str]) -> int:
    """잡 우선순위 (작을수록 먼저 dequeue). 우선순위 큐의 값 SoT — via/kind 에서만 도출 (ADR 0009).
    user(via=watch/preview)=0 > reprobe(kind=reprobe)=1 > batch-retry(via=batch-retry)=2 > batch(via=batch)=3.
    batch 계열만 deprioritize — 그 외 register 는 전부 interactive 라 최우선(0).
    batch 안에서 2단: 신규 catalog bulk(via=batch)=3 < 재시도/테스트(via=batch-retry)=2.
    한 batch 끝내고 그 실패분을 retry/테스트(register_batch.py --failed/--rc/--force/--url) 돌리는 중에
    다른 catalog bulk 를 동시 enqueue 하면, retry 가 새 bulk backlog 보다 먼저 dequeue 된다."""
    if via == "batch":
        return 3
    if via == "batch-retry":
        return 2
    if kind == "reprobe":
        return 1
    return 0


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
    priority = _derive_priority(kind, via)
    def _do():
        cur = conn.execute(
            "INSERT INTO jobs(kind,url,slug,article_url,via,requested_by,ack_channel_id,ack_message_id,sub_payload,"
            "status,created_at,priority) VALUES(?,?,?,?,?,?,?,?,?, 'pending', ?,?)",
            (kind, url, slug, article_url, via, requested_by, ack_channel_id, ack_message_id, sub_payload, _now_iso(), priority),
        )
        conn.commit()
        return int(cur.lastrowid)
    return _retry(_do), True


def claim_next_pending(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    """가장 오래된 pending 잡 하나를 running 으로 표시하고 반환. 없으면 None.

    pool_size>1 + per-slug 직렬화: slug 이 이미 다른 worker 의 running 잡이면 *그 잡은 스킵* 하고
    다음 pending 후보로 넘어감. 모든 pending slug 이 in-flight 면 None — 호출자가 idle sleep 후 재시도.
    우선순위 큐 (ADR 0009): dequeue 순서 = ORDER BY priority ASC, id ASC (작은 priority 먼저, 동순위는
    FIFO). *non-blocked* pending 들 사이에서 유지. running 끝난 slug 의 pending 도 같은 정렬.

    SELECT-then-UPDATE 패턴 (Python sqlite3 의 implicit 트랜잭션과 충돌 없도록 BEGIN IMMEDIATE 피함).
    UPDATE WHERE status='pending' 조건으로 race 가드 — 다른 워커가 같은 잡 채갔으면 rowcount=0, 다음 잡으로.
    """
    for _ in range(8):
        row = conn.execute(
            "SELECT id FROM jobs WHERE status='pending' "
            "AND slug NOT IN (SELECT slug FROM jobs WHERE status='running') "
            "ORDER BY priority ASC, id ASC LIMIT 1"
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
    """이 잡의 큐 위치 (1-base). 이미 running 이면 0, done/failed 면 -1, 없는 잡이면 -1.

    우선순위 큐 (ADR 0009) — claim 정렬(priority ASC, id ASC)과 같은 기준으로 *앞에 dequeue 될*
    pending 수를 셈: priority 가 더 낮거나(=먼저), 같은 priority 면서 id≤. id 단독 카운트면 뒤로
    정렬되는 batch backlog 를 앞에 세어 ack 'N번째' 가 거짓이 됨.
    """
    row = conn.execute("SELECT status, priority FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        return -1
    if row["status"] == "running":
        return 0
    if row["status"] in ("done", "failed"):
        return -1
    return int(conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE status='pending' "
        "AND (priority < ? OR (priority = ? AND id <= ?))",
        (row["priority"], row["priority"], job_id),
    ).fetchone()[0])


def queue_pending_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM jobs WHERE status='pending'").fetchone()[0])


def find_earlier_same_slug_job(conn: sqlite3.Connection, slug: str, *, exclude_id: int) -> Optional[int]:
    """주어진 slug 의 다른 pending/running 잡 (exclude_id 제외) 중 가장 빠른 id 반환. 없으면 None.
    K1/K3 같은 URL 동시 처리 시 사용자 ack 에 "이미 처리 중인 잡 #N" 표시용."""
    row = conn.execute(
        "SELECT id FROM jobs WHERE slug=? AND id<>? AND status IN ('pending','running') "
        "ORDER BY id ASC LIMIT 1",
        (slug, exclude_id),
    ).fetchone()
    return int(row["id"]) if row else None


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


def recent_register_jobs(conn: sqlite3.Connection, limit: int = 20,
                         offset: int = 0,
                         status: Optional[str] = None) -> list[sqlite3.Row]:
    """사용자 `/watch`·`/preview` 가 만든 잡만(=kind='register') 최신 순. inspector.recent_jobs 가 호출.

    `status` (pending/running/done/failed) 가 주어지면 SQL `WHERE status=?` pushdown — Python 쪽
    post-filter 가 LIMIT 윈도우 밖 행 누락하는 문제 방지 (대시보드 `/jobs?status=X`).
    """
    if status is None:
        return conn.execute(
            "SELECT * FROM jobs WHERE kind='register' ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM jobs WHERE kind='register' AND status=? ORDER BY id DESC LIMIT ? OFFSET ?",
        (status, limit, offset),
    ).fetchall()


# --------------------------------------------------------------------------- #
# reports (`/report`) — open/resolved 만 사용. admin triage 와 inspector.diagnose 가 enrich.
# --------------------------------------------------------------------------- #
def add_report(conn: sqlite3.Connection, *, user_id: str, username: Optional[str],
               slug: Optional[str], issue: str, url: Optional[str] = None) -> int:
    def _do():
        cur = conn.execute(
            "INSERT INTO reports(user_id,username,slug,url,issue,created_at,status) "
            "VALUES(?,?,?,?,?, ?, 'open')",
            (user_id, username, slug, url, issue, _now_iso()),
        )
        conn.commit()
        return int(cur.lastrowid)
    return _retry(_do)


def list_reports(conn: sqlite3.Connection, *, status: Optional[str] = "open",
                 limit: int = 50, offset: int = 0) -> list[sqlite3.Row]:
    """status=None 이면 전체. 기본 open 만 최신순."""
    if status is None:
        return conn.execute(
            "SELECT * FROM reports ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM reports WHERE status=? ORDER BY id DESC LIMIT ? OFFSET ?",
        (status, limit, offset),
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


def list_feedback(conn: sqlite3.Connection, limit: int = 20,
                  offset: int = 0) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM feedback ORDER BY id DESC LIMIT ? OFFSET ?",
        (limit, offset),
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


# --------------------------------------------------------------------------- #
# ADR 0017 — poll/notify runs 추적
#
# 설계 원칙 (§2f):
#   - 모든 helper 는 best-effort. fail 시 transaction rollback + stderr 1줄 + 호출자에게 영향 X.
#   - poll_run_start 가 None 반환 시 (DB 에러 등), 후속 helper 가 run_id=None 보면 곧장 skip.
#   - 사이트 isolation = ADR 0016 그대로. tracking 은 그 위에 *얹는* 영구 기록.
# --------------------------------------------------------------------------- #
import os as _os
import socket as _socket
import sys as _sys

# reaper 임계 — ADR 0017 §2e. anti-bot 사이트 wall-clock 안전 margin.
_POLL_REAP_THRESHOLD_S = 2 * 60 * 60      # 2h
_NOTIFY_REAP_THRESHOLD_S = 15 * 60         # 15min


def _tracking_warn(fn_name: str, exc: BaseException) -> None:
    """tracking helper 실패 stderr 1줄. 호출자에게 영향 X."""
    print(f"[tracking] ⚠ {fn_name} failed: {type(exc).__name__}: {exc}", file=_sys.stderr, flush=True)


def _pid_alive(pid: int) -> Optional[bool]:
    """현 host 의 pid 살아있나? Linux/Mac = os.kill(pid,0). Windows / 모르면 None."""
    if pid <= 0:
        return False
    try:
        # Windows 에서는 os.kill 이 동작하지만 signal 0 의미 다름 — None 반환해 reaper 가 fallback.
        if _sys.platform.startswith("win"):
            return None
        _os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:  # noqa: BLE001
        return None


def _here_host() -> str:
    try:
        return _socket.gethostname()
    except Exception:  # noqa: BLE001
        return ""


def poll_run_start(conn: sqlite3.Connection, *, run_label: str, pid: int,
                   git_sha: Optional[str] = None,
                   args_json: Optional[str] = None,
                   n_sites: Optional[int] = None) -> Optional[int]:
    """ADR 0017 — poll 시작 시 row INSERT. 반환 = run_id (또는 fail 시 None).

    같은 함수가 reaper 도 호출 — 옛 status='running' row 정리. best-effort."""
    try:
        reap_stale_poll_runs(conn)
    except Exception as e:  # noqa: BLE001
        _tracking_warn("reap_stale_poll_runs", e)
    try:
        cur = conn.execute(
            "INSERT INTO poll_runs(run_label,started_at,pid,host,git_sha,args_json,n_sites,status) "
            "VALUES(?,?,?,?,?,?,?,'running')",
            (run_label, _now_iso(), pid, _here_host(), git_sha, args_json, n_sites),
        )
        conn.commit()
        return int(cur.lastrowid)
    except Exception as e:  # noqa: BLE001
        try:
            conn.rollback()
        except Exception:
            pass
        _tracking_warn("poll_run_start", e)
        return None


def poll_run_finish(conn: sqlite3.Connection, run_id: Optional[int], *,
                    n_done: int, n_timeout: int, n_error: int,
                    n_lurking_skipped: int,
                    n_attempted_unique: int, n_inserted: int,
                    n_present_after: int, persist_mismatch_sites: int,
                    duration_ms: int) -> None:
    """poll 정상 종료 시 UPDATE. run_id=None 이면 skip."""
    if run_id is None:
        return
    try:
        conn.execute(
            "UPDATE poll_runs SET ended_at=?, n_done=?, n_timeout=?, n_error=?, "
            "n_lurking_skipped=?, n_attempted_unique=?, n_inserted=?, n_present_after=?, "
            "persist_mismatch_sites=?, duration_ms=?, status='done' "
            "WHERE id=? AND status='running'",
            (_now_iso(), n_done, n_timeout, n_error, n_lurking_skipped,
             n_attempted_unique, n_inserted, n_present_after, persist_mismatch_sites,
             duration_ms, run_id),
        )
        conn.commit()
    except Exception as e:  # noqa: BLE001
        try:
            conn.rollback()
        except Exception:
            pass
        _tracking_warn("poll_run_finish", e)


def poll_site_run_finish(conn: sqlite3.Connection, *, run_id: Optional[int], slug: str,
                         started_at: str, ended_at: str, status: str,
                         n_posts: int = 0, n_new: int = 0,
                         n_attempted_unique: int = 0, n_inserted: int = 0,
                         n_present_after: int = 0,
                         duration_ms: Optional[int] = None,
                         lock_wait_ms: Optional[int] = None,
                         error_msg: Optional[str] = None,
                         note: Optional[str] = None) -> None:
    """ADR 0017 — 사이트 1회 완료 시 INSERT. run_id=None 이면 skip. INSERT OR IGNORE
    (UNIQUE(run_id, slug)) — reaper 의 _unknown_ row 와 race 시 정상 finish 가 우선.

    ADR 0019 Phase 1 — lock_wait_ms = chromium flock 획득 대기 시간(ms). chromium 사이트만 박힘,
    httpx 사이트는 NULL. duration_ms 와 분리 — duration_ms = fetch (wait_for 안) 만.
    """
    if run_id is None:
        return
    try:
        conn.execute(
            "INSERT OR IGNORE INTO poll_site_runs(run_id,slug,started_at,ended_at,status,"
            "n_posts,n_new,n_attempted_unique,n_inserted,n_present_after,"
            "duration_ms,lock_wait_ms,error_msg,note) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, slug, started_at, ended_at, status,
             n_posts, n_new, n_attempted_unique, n_inserted, n_present_after,
             duration_ms, lock_wait_ms, error_msg, note),
        )
        conn.commit()
    except Exception as e:  # noqa: BLE001
        try:
            conn.rollback()
        except Exception:
            pass
        _tracking_warn("poll_site_run_finish", e)


def reap_stale_poll_runs(conn: sqlite3.Connection) -> int:
    """ADR 0017 §2e — 옛 status='running' poll_runs 를 crashed 로 마킹.
    같은 host 면 pid liveness 체크 (Linux/Mac). 다른 host 면 단순 timeout. 반환 = reaped row 수.

    codex MED — 전체 함수 best-effort 가드. 최초 SELECT 도 실패할 수 있음 (closed conn 등).
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=_POLL_REAP_THRESHOLD_S)).isoformat()
    here = _here_host()
    try:
        candidates = conn.execute(
            "SELECT id, host, pid, started_at, n_sites FROM poll_runs "
            "WHERE status='running' AND started_at < ?",
            (cutoff,),
        ).fetchall()
    except Exception as e:  # noqa: BLE001
        try:
            conn.rollback()
        except Exception:
            pass
        _tracking_warn("reap_stale_poll_runs:select", e)
        return 0
    n_reaped = 0
    for r in candidates:
        # liveness 체크 — 같은 host 면 pid alive 시 reap skip
        if r["host"] == here:
            alive = _pid_alive(int(r["pid"]))
            if alive is True:
                continue
            reason = "liveness_dead" if alive is False else "stale_timeout"
        else:
            reason = "stale_timeout"
        now = _now_iso()
        try:
            conn.execute(
                "UPDATE poll_runs SET status='crashed', reaped_at=?, reap_reason=?, "
                "ended_at=COALESCE(ended_at, ?) "
                "WHERE id=? AND status='running'",
                (now, reason, now, r["id"]),
            )
            # child reaper — 그 run 에 finish 못 박힌 사이트 수 만큼 _unknown_ row 1건.
            n_recorded = int(conn.execute(
                "SELECT COUNT(*) FROM poll_site_runs WHERE run_id=?", (r["id"],)
            ).fetchone()[0])
            delta = int((r["n_sites"] or 0) - n_recorded)
            if delta > 0:
                conn.execute(
                    "INSERT OR IGNORE INTO poll_site_runs(run_id,slug,started_at,ended_at,status,"
                    "error_msg,note) VALUES(?,?,?,?,?,?,?)",
                    (r["id"], "_unknown_", r["started_at"], now, "run_crashed",
                     f"reaper: parent crashed ({reason}), site finish not recorded",
                     f"missing_count={delta}"),
                )
            conn.commit()
            n_reaped += 1
        except Exception as e:  # noqa: BLE001
            try:
                conn.rollback()
            except Exception:
                pass
            _tracking_warn(f"reap_poll_runs(id={r['id']})", e)
    return n_reaped


def notify_run_start(conn: sqlite3.Connection, *, pid: int,
                     args_json: Optional[str] = None,
                     now_hhmm: Optional[str] = None,
                     today_kst: Optional[str] = None,
                     n_due_targets: int = 0) -> Optional[int]:
    """ADR 0017 — deliver_due 시작 시 row INSERT. 반환 = run_id (또는 None)."""
    try:
        reap_stale_notify_runs(conn)
    except Exception as e:  # noqa: BLE001
        _tracking_warn("reap_stale_notify_runs", e)
    try:
        cur = conn.execute(
            "INSERT INTO notify_runs(started_at,pid,host,args_json,now_hhmm,today_kst,"
            "n_due_targets,status) VALUES(?,?,?,?,?,?,?,'running')",
            (_now_iso(), pid, _here_host(), args_json, now_hhmm, today_kst, n_due_targets),
        )
        conn.commit()
        return int(cur.lastrowid)
    except Exception as e:  # noqa: BLE001
        try:
            conn.rollback()
        except Exception:
            pass
        _tracking_warn("notify_run_start", e)
        return None


def notify_run_finish(conn: sqlite3.Connection, run_id: Optional[int], *,
                      n_targets_ok: int, n_targets_failed: int,
                      n_posts_delivered: int, n_empty_notices: int,
                      duration_ms: int) -> None:
    if run_id is None:
        return
    try:
        conn.execute(
            "UPDATE notify_runs SET ended_at=?, n_targets_ok=?, n_targets_failed=?, "
            "n_posts_delivered=?, n_empty_notices=?, duration_ms=?, status='done' "
            "WHERE id=? AND status='running'",
            (_now_iso(), n_targets_ok, n_targets_failed, n_posts_delivered, n_empty_notices,
             duration_ms, run_id),
        )
        conn.commit()
    except Exception as e:  # noqa: BLE001
        try:
            conn.rollback()
        except Exception:
            pass
        _tracking_warn("notify_run_finish", e)


def notify_target_run_finish(conn: sqlite3.Connection, *, run_id: Optional[int],
                             target_kind: str, target_id: str,
                             started_at: str, ended_at: str, status: str,
                             n_posts: int = 0, n_chunks: int = 0,
                             duration_ms: Optional[int] = None,
                             error_msg: Optional[str] = None) -> None:
    if run_id is None:
        return
    try:
        conn.execute(
            "INSERT OR IGNORE INTO notify_target_runs(run_id,target_kind,target_id,started_at,"
            "ended_at,status,n_posts,n_chunks,duration_ms,error_msg) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (run_id, target_kind, target_id, started_at, ended_at, status,
             n_posts, n_chunks, duration_ms, error_msg),
        )
        conn.commit()
    except Exception as e:  # noqa: BLE001
        try:
            conn.rollback()
        except Exception:
            pass
        _tracking_warn("notify_target_run_finish", e)


def reap_stale_notify_runs(conn: sqlite3.Connection) -> int:
    """ADR 0017 — 옛 status='running' notify_runs 정리. child reaping 포함 (codex MED)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=_NOTIFY_REAP_THRESHOLD_S)).isoformat()
    here = _here_host()
    try:
        candidates = conn.execute(
            "SELECT id, host, pid, started_at, n_due_targets FROM notify_runs "
            "WHERE status='running' AND started_at < ?",
            (cutoff,),
        ).fetchall()
    except Exception as e:  # noqa: BLE001
        try:
            conn.rollback()
        except Exception:
            pass
        _tracking_warn("reap_stale_notify_runs:select", e)
        return 0
    n_reaped = 0
    for r in candidates:
        if r["host"] == here:
            alive = _pid_alive(int(r["pid"]))
            if alive is True:
                continue
            reason = "liveness_dead" if alive is False else "stale_timeout"
        else:
            reason = "stale_timeout"
        now = _now_iso()
        try:
            conn.execute(
                "UPDATE notify_runs SET status='crashed', reaped_at=?, reap_reason=?, "
                "ended_at=COALESCE(ended_at, ?) "
                "WHERE id=? AND status='running'",
                (now, reason, now, r["id"]),
            )
            # codex MED — child reaper: finish 안 박힌 target 수 만큼 _unknown_ sentinel 1건.
            n_recorded = int(conn.execute(
                "SELECT COUNT(*) FROM notify_target_runs WHERE run_id=?", (r["id"],)
            ).fetchone()[0])
            delta = int((r["n_due_targets"] or 0) - n_recorded)
            if delta > 0:
                conn.execute(
                    "INSERT OR IGNORE INTO notify_target_runs(run_id,target_kind,target_id,"
                    "started_at,ended_at,status,error_msg) VALUES(?,?,?,?,?,?,?)",
                    (r["id"], "_unknown_", "_unknown_", r["started_at"], now, "run_crashed",
                     f"reaper: parent crashed ({reason}), target finish not recorded; missing_count={delta}"),
                )
            conn.commit()
            n_reaped += 1
        except Exception as e:  # noqa: BLE001
            try:
                conn.rollback()
            except Exception:
                pass
            _tracking_warn(f"reap_notify_runs(id={r['id']})", e)
    return n_reaped


# --------------------------------------------------------------------------- #
# dashboard 조회 helper — /runs 페이지
# --------------------------------------------------------------------------- #
def recent_poll_runs(conn: sqlite3.Connection, *, limit: int = 100,
                     status: Optional[str] = None) -> list[sqlite3.Row]:
    if status:
        return conn.execute(
            "SELECT * FROM poll_runs WHERE status=? ORDER BY started_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM poll_runs ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()


def get_poll_run(conn: sqlite3.Connection, run_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM poll_runs WHERE id=?", (run_id,)).fetchone()


def poll_site_runs_for(conn: sqlite3.Connection, run_id: int, *,
                       slug: Optional[str] = None,
                       status: Optional[str] = None) -> list[sqlite3.Row]:
    sql = "SELECT * FROM poll_site_runs WHERE run_id=?"
    params: list = [run_id]
    if slug:
        sql += " AND slug=?"
        params.append(slug)
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY id ASC"
    return conn.execute(sql, params).fetchall()


def recent_notify_runs(conn: sqlite3.Connection, *, limit: int = 100,
                       status: Optional[str] = None) -> list[sqlite3.Row]:
    if status:
        return conn.execute(
            "SELECT * FROM notify_runs WHERE status=? ORDER BY started_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM notify_runs ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()


def get_notify_run(conn: sqlite3.Connection, run_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM notify_runs WHERE id=?", (run_id,)).fetchone()


def notify_target_runs_for(conn: sqlite3.Connection, run_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM notify_target_runs WHERE run_id=? ORDER BY id ASC", (run_id,)
    ).fetchall()


def prune_runs(conn: sqlite3.Connection, *, poll_keep_days: int = 90,
               site_keep_days: int = 30, notify_keep_days: int = 90) -> dict:
    """ADR 0017 — TTL GC. poll_runs/notify_runs 90d, poll_site_runs 30d.

    poll_runs 가 site 보다 길게 유지되는 이유: per-site detail 은 단기 진단 데이터지만,
    run 단위 (언제 어떤 git_sha 로 폴링했나) 는 사후 분석에서 더 자주 본다."""
    now = datetime.now(timezone.utc)
    poll_cutoff = (now - timedelta(days=poll_keep_days)).isoformat()
    site_cutoff = (now - timedelta(days=site_keep_days)).isoformat()
    notify_cutoff = (now - timedelta(days=notify_keep_days)).isoformat()
    out = {"poll_runs": 0, "poll_site_runs": 0, "notify_runs": 0, "notify_target_runs": 0}
    try:
        c = conn.execute("DELETE FROM poll_site_runs WHERE started_at < ?", (site_cutoff,))
        out["poll_site_runs"] = c.rowcount
        c = conn.execute("DELETE FROM notify_target_runs WHERE started_at < ?", (notify_cutoff,))
        out["notify_target_runs"] = c.rowcount
        c = conn.execute("DELETE FROM poll_runs WHERE started_at < ?", (poll_cutoff,))
        out["poll_runs"] = c.rowcount
        c = conn.execute("DELETE FROM notify_runs WHERE started_at < ?", (notify_cutoff,))
        out["notify_runs"] = c.rowcount
        conn.commit()
    except Exception as e:  # noqa: BLE001
        try:
            conn.rollback()
        except Exception:
            pass
        _tracking_warn("prune_runs", e)
    return out
