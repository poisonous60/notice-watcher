"""ADR 0019 Phase 2a — generic jobs schema 마이그 + enqueue_job 회귀 테스트.

- 옛 jobs 스키마 (kind CHECK in ('register','reprobe'), url/slug NOT NULL) fixture 생성.
- connect() 가 _migrate_check_enum 으로 rebuild → 새 enum + 새 컬럼 (dedupe_key, requeue_at) +
  url/slug NULL OK.
- 새 kind 인 'poll_site' / 'deliver_target' enqueue 동작.
- dedupe_key partial UNIQUE 가 race-safe — 두 번째 INSERT 가 기존 row id 반환 (newly=False).
- 옛 (kind, slug) fallback dedupe 도 유지.
- priority canonical 표 (ADR 0019 §2g) 0/1/2/3/4/5 dequeue 순서.
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# 옛 jobs schema — ADR 0019 이전 (kind 2종, url/slug NOT NULL, dedupe_key/requeue_at 없음).
_LEGACY_JOBS_SQL = """
CREATE TABLE jobs (
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
    priority        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_jobs_status ON jobs(status, id);
CREATE INDEX idx_jobs_slug ON jobs(slug);
"""


def _legacy_db_path() -> Path:
    """옛 jobs 스키마 + register row 1개를 가진 DB fixture 생성."""
    p = Path(tempfile.mkdtemp(prefix="jobs_migrate_")) / "bot.sqlite3"
    raw = sqlite3.connect(str(p))
    raw.executescript(_LEGACY_JOBS_SQL)
    raw.execute(
        "INSERT INTO jobs(kind,url,slug,via,status,created_at,priority) "
        "VALUES('register','https://example.com/old','old_slug','batch','pending','2026-01-01T00:00:00Z',3)"
    )
    raw.commit()
    raw.close()
    return p


def _test_migrate_then_enqueue_new_kinds() -> tuple[str, bool, str]:
    """connect() 가 옛 jobs schema 를 rebuild → 새 enum 인 'poll_site' / 'deliver_target' enqueue OK."""
    p = _legacy_db_path()
    from bot import db
    conn = db.connect(p)
    try:
        # 새 컬럼 존재 확인
        cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        for must in ("dedupe_key", "requeue_at"):
            if must not in cols:
                return ("migrate_new_kinds", False, f"after rebuild '{must}' column missing — cols={sorted(cols)}")
        # 옛 register row 살아있는지
        n_old = conn.execute("SELECT COUNT(*) FROM jobs WHERE slug='old_slug'").fetchone()[0]
        if n_old != 1:
            return ("migrate_new_kinds", False, f"옛 register row 손실 — n={n_old}")
        # 새 kind enqueue
        jid_p, ins_p = db.enqueue_job(conn, kind="poll_site", url="https://x.example/notice",
                                        slug="x_slug", dedupe_key="poll:42:x_slug",
                                        sub_payload='{"run_id":42}')
        if not ins_p:
            return ("migrate_new_kinds", False, "poll_site newly_inserted False")
        jid_d, ins_d = db.enqueue_job(conn, kind="deliver_target",
                                        dedupe_key="deliver:dm:123:2026-05-25",
                                        sub_payload='{"target_kind":"dm","target_id":"123","today_kst":"2026-05-25"}')
        if not ins_d:
            return ("migrate_new_kinds", False, "deliver_target newly_inserted False")
        # url/slug 없는 deliver_target 박혔는지
        row = conn.execute("SELECT kind, url, slug FROM jobs WHERE id=?", (jid_d,)).fetchone()
        if row["kind"] != "deliver_target" or row["url"] is not None or row["slug"] is not None:
            return ("migrate_new_kinds", False,
                    f"deliver_target row 이상: kind={row['kind']} url={row['url']!r} slug={row['slug']!r}")
        return ("migrate_new_kinds", True, f"poll_site #{jid_p} + deliver_target #{jid_d} OK")
    finally:
        conn.close()


def _test_dedupe_key_partial_unique() -> tuple[str, bool, str]:
    """같은 dedupe_key 로 두 번 enqueue → 두 번째는 기존 id, newly=False."""
    p = _legacy_db_path()
    from bot import db
    conn = db.connect(p)
    try:
        jid1, ins1 = db.enqueue_job(conn, kind="deliver_target",
                                     dedupe_key="deliver:dm:777:2026-05-25")
        jid2, ins2 = db.enqueue_job(conn, kind="deliver_target",
                                     dedupe_key="deliver:dm:777:2026-05-25")
        if not (ins1 and not ins2):
            return ("dedupe_key", False, f"1차 ins={ins1} 2차 ins={ins2} (기대 True/False)")
        if jid1 != jid2:
            return ("dedupe_key", False, f"id mismatch jid1={jid1} jid2={jid2}")
        return ("dedupe_key", True, f"dedupe_key 충돌 시 same id {jid1} (newly=False)")
    finally:
        conn.close()


def _test_legacy_kind_slug_dedupe() -> tuple[str, bool, str]:
    """dedupe_key 미지정 + dedupe=True 면 (kind, slug) fallback."""
    p = _legacy_db_path()
    from bot import db
    conn = db.connect(p)
    try:
        # 옛 'old_slug' register 가 이미 pending. 같은 (register, old_slug) 재시도 → 같은 id.
        jid, ins = db.enqueue_job(conn, kind="register", url="https://example.com/old",
                                   slug="old_slug", via="watch", dedupe=True)
        if ins:
            return ("legacy_dedupe", False, "newly_inserted True (기대 False — 옛 register row 와 dedupe)")
        return ("legacy_dedupe", True, f"fallback dedupe 동작 — id={jid}")
    finally:
        conn.close()


def _test_priority_canonical() -> tuple[str, bool, str]:
    """ADR 0019 §2g: 0=user > 1=reprobe > 2=deliver_target > 3=poll_site > 4=batch-retry > 5=batch."""
    p = _legacy_db_path()
    from bot import db
    conn = db.connect(p)
    try:
        # 6 잡 enqueue (역순) → claim 순서가 canonical 순서대로 나와야 함.
        # cleanup — 옛 fixture register 잡 제거 (slug 충돌 회피)
        conn.execute("DELETE FROM jobs"); conn.commit()
        kinds = [
            ("register", "batch", "https://x.com/a", "slug_batch"),       # priority 5
            ("register", "batch-retry", "https://x.com/b", "slug_retry"), # priority 4
            ("poll_site", None, "https://x.com/c", "slug_poll"),          # priority 3
            ("deliver_target", None, None, None),                          # priority 2
            ("reprobe", None, "https://x.com/e", "slug_reprobe"),         # priority 1
            ("register", "watch", "https://x.com/f", "slug_user"),        # priority 0
        ]
        for k, v, u, s in kinds:
            dk = f"test:{k}:{v or ''}"
            db.enqueue_job(conn, kind=k, url=u, slug=s, via=v, dedupe_key=dk)
        # claim 순서 — _derive_priority 가 매긴 priority 컬럼 기준 ORDER BY priority ASC, id ASC.
        rows = conn.execute(
            "SELECT kind, via, priority FROM jobs WHERE status='pending' "
            "ORDER BY priority ASC, id ASC"
        ).fetchall()
        seq = [(r["kind"], r["via"], r["priority"]) for r in rows]
        expected_priorities = [0, 1, 2, 3, 4, 5]
        actual_priorities = [s[2] for s in seq]
        if actual_priorities != expected_priorities:
            return ("priority_canonical", False,
                    f"순서 mismatch — expected {expected_priorities} actual {actual_priorities} (seq={seq})")
        return ("priority_canonical", True, f"순서 OK {seq}")
    finally:
        conn.close()


def _test_register_kind_requires_url_slug() -> tuple[str, bool, str]:
    """register/reprobe 는 url/slug 필수 — 누락 시 ValueError."""
    p = _legacy_db_path()
    from bot import db
    conn = db.connect(p)
    try:
        try:
            db.enqueue_job(conn, kind="register", slug="x")  # url 없음
        except ValueError as e:
            if "requires url and slug" in str(e):
                return ("register_requires", True, f"ValueError 정상 발생 — {e}")
            return ("register_requires", False, f"잘못된 ValueError 메시지: {e}")
        return ("register_requires", False, "기대 = ValueError, 실제 = 정상 진행")
    finally:
        conn.close()


def _test_reject_rcs_finish_as_rejected() -> tuple[str, bool, str]:
    """rc=2/3/4 are terminal normal rejects, not gen/system failures."""
    p = _legacy_db_path()
    from bot import db
    conn = db.connect(p)
    try:
        conn.execute("DELETE FROM jobs"); conn.commit()
        got: dict[int, str] = {}
        for rc in (2, 3, 4, 1):
            jid, inserted = db.enqueue_job(
                conn, kind="register",
                url=f"https://x.example/{rc}",
                slug=f"slug_{rc}",
                via="batch-retry",
            )
            if not inserted:
                return ("reject_rc_status", False, f"enqueue unexpectedly deduped rc={rc}")
            row = db.claim_next_pending(conn)
            if row is None or row["id"] != jid:
                return ("reject_rc_status", False, f"claim mismatch rc={rc} row={dict(row) if row else None}")
            db.mark_job_finished(conn, jid, ok=False, rc=rc, tail=f"rc={rc}")
            out = conn.execute("SELECT status FROM jobs WHERE id=?", (jid,)).fetchone()
            got[rc] = out["status"] if out else "<missing>"
            pos = db.queue_position(conn, jid)
            if pos != -1:
                return ("reject_rc_status", False, f"terminal rc={rc} queue_position={pos}")
        expected = {2: "rejected", 3: "rejected", 4: "rejected", 1: "failed"}
        if got != expected:
            return ("reject_rc_status", False, f"status mismatch expected={expected} got={got}")
        summary = db.jobs_summary(conn)
        if summary.get("rejected") != 3 or summary.get("failed") != 1:
            return ("reject_rc_status", False, f"summary mismatch: {summary}")
        return ("reject_rc_status", True, f"statuses={got} summary={summary}")
    finally:
        conn.close()


def run() -> list[tuple[str, bool, str]]:
    return [
        _test_migrate_then_enqueue_new_kinds(),
        _test_dedupe_key_partial_unique(),
        _test_legacy_kind_slug_dedupe(),
        _test_priority_canonical(),
        _test_register_kind_requires_url_slug(),
        _test_reject_rcs_finish_as_rejected(),
    ]


def test_jobs_schema_migrate_cases():
    results = run()
    failed = [(n, d) for n, ok, d in results if not ok]
    assert not failed, "\n".join(f"{n}: {d}" for n, d in failed)


if __name__ == "__main__":
    results = run()
    failed = [(n, d) for n, ok, d in results if not ok]
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {d}")
    if failed:
        print(f"\n{len(failed)} FAILED")
        sys.exit(1)
    print(f"\n{len(results)} passed")
