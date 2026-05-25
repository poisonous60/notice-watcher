"""ADR 0017 — poll/notify runs 추적 + 영속화 검증 단위 테스트.

테스트 범위:
  - schema 적용 (poll_runs/poll_site_runs/notify_runs/notify_target_runs)
  - poll_run_start/finish 라운드 트립
  - poll_site_run_finish — UNIQUE(run_id, slug) 멱등성
  - persist verification — partial persist (5건 시도 → 2건 박힘) 시나리오
  - reaper — stale 'running' row 를 'crashed' 로 마킹 + child reaper
  - tracking helper best-effort — DB 닫혀도 호출자 영향 X
  - notify_run flow 동일 패턴
  - prune_runs TTL GC
"""
from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _conn() -> sqlite3.Connection:
    from bot import db
    p = Path(tempfile.mkdtemp()) / "t.sqlite3"
    return db.connect(p)


def run() -> list[tuple[str, bool, str]]:
    from bot import db
    cases: list[tuple[str, bool, str]] = []

    # ----- 1. schema — 4 테이블 존재 + 필요 컬럼 -----
    conn = _conn()
    for tbl, expect_cols in (
        ("poll_runs", {"run_label", "git_sha", "persist_mismatch_sites", "status"}),
        ("poll_site_runs", {"run_id", "slug", "n_attempted_unique", "n_inserted",
                             "n_present_after", "status"}),
        ("notify_runs", {"now_hhmm", "today_kst", "n_due_targets", "status"}),
        ("notify_target_runs", {"target_kind", "target_id", "n_chunks", "status"}),
    ):
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()}
        missing = expect_cols - cols
        cases.append((f"schema_{tbl}", not missing, f"missing={missing}"))

    # ----- 2. poll_run round-trip -----
    rid = db.poll_run_start(conn, run_label="lab1", pid=111, git_sha="abc12345",
                             args_json='["--sites","s1"]', n_sites=2)
    cases.append(("poll_run_start_returns_id", rid is not None and rid > 0, f"got {rid}"))

    db.poll_run_finish(conn, rid, n_done=2, n_timeout=0, n_error=0, n_lurking_skipped=5,
                       n_attempted_unique=3, n_inserted=3, n_present_after=3,
                       persist_mismatch_sites=0, duration_ms=12000)
    r = db.get_poll_run(conn, rid)
    cases.append(("poll_run_finish_status_done", r["status"] == "done", f"got {r['status']}"))
    cases.append(("poll_run_finish_counters_persist",
                  r["n_done"] == 2 and r["n_lurking_skipped"] == 5 and r["n_inserted"] == 3,
                  f"got {dict(r)}"))

    # ----- 3. poll_site_run_finish UNIQUE 멱등 — 두 번 호출해도 첫 row 유지 -----
    db.poll_site_run_finish(conn, run_id=rid, slug="siteA",
                             started_at="2026-05-25T00:00:00+00:00",
                             ended_at="2026-05-25T00:00:05+00:00",
                             status="ok", n_posts=10, n_new=2, duration_ms=5000)
    db.poll_site_run_finish(conn, run_id=rid, slug="siteA",
                             started_at="2026-05-25T00:00:00+00:00",
                             ended_at="2026-05-25T00:00:10+00:00",
                             status="poll_timeout", n_posts=0, n_new=0, duration_ms=10000)
    sites = db.poll_site_runs_for(conn, rid, slug="siteA")
    cases.append(("poll_site_unique_idempotent",
                  len(sites) == 1 and sites[0]["status"] == "ok" and sites[0]["n_new"] == 2,
                  f"got {[dict(s) for s in sites]}"))

    # ----- 4. persist mismatch 시나리오 시뮬레이션 — note + missing_ids 검출 -----
    db.poll_site_run_finish(conn, run_id=rid, slug="siteMis",
                             started_at="2026-05-25T00:00:00+00:00",
                             ended_at="2026-05-25T00:00:08+00:00",
                             status="persist_mismatch",
                             n_posts=5, n_new=5,
                             n_attempted_unique=5, n_inserted=2, n_present_after=2,
                             duration_ms=8000,
                             note='{"missing_ids": ["x", "y", "z"]}')
    sites = db.poll_site_runs_for(conn, rid, status="persist_mismatch")
    cases.append(("persist_mismatch_recorded",
                  len(sites) == 1 and sites[0]["n_present_after"] == 2
                  and "missing_ids" in (sites[0]["note"] or ""),
                  f"got {[dict(s) for s in sites]}"))

    # ----- 5. reaper — stale 'running' row 를 'crashed' 박음 + 'running' 새 row 안 건드림 -----
    conn2 = _conn()
    # 가짜 stale row 박음: started_at = 3h 전, pid=999999 (없을 가능성 큼)
    stale = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    conn2.execute(
        "INSERT INTO poll_runs(run_label,started_at,pid,host,n_sites,status) "
        "VALUES('stale','" + stale + "',999999,'__fake_host__',5,'running')")
    conn2.commit()
    n_reaped = db.reap_stale_poll_runs(conn2)
    cases.append(("reaper_marks_stale", n_reaped >= 1, f"n_reaped={n_reaped}"))
    stale_row = conn2.execute(
        "SELECT status, reap_reason FROM poll_runs WHERE run_label='stale'").fetchone()
    cases.append(("reaper_status_crashed", stale_row["status"] == "crashed",
                  f"got {dict(stale_row)}"))
    cases.append(("reaper_reason_set", stale_row["reap_reason"] in
                  ("stale_timeout", "liveness_dead"), f"got {stale_row['reap_reason']}"))
    # child reaper: _unknown_ row 박혀있어야 함 (n_sites=5, finish 0 → delta=5)
    unk = conn2.execute(
        "SELECT note FROM poll_site_runs WHERE slug='_unknown_' AND status='run_crashed'"
    ).fetchone()
    cases.append(("reaper_child_unknown_row",
                  unk is not None and "missing_count=5" in (unk["note"] or ""),
                  f"got {dict(unk) if unk else None}"))

    # ----- 6. reaper 가 fresh 'running' (5min 전) 는 안 건드림 -----
    fresh = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    conn2.execute(
        "INSERT INTO poll_runs(run_label,started_at,pid,host,n_sites,status) "
        "VALUES('fresh','" + fresh + "',1,'h',1,'running')")
    conn2.commit()
    db.reap_stale_poll_runs(conn2)
    fresh_row = conn2.execute(
        "SELECT status FROM poll_runs WHERE run_label='fresh'").fetchone()
    cases.append(("reaper_skips_fresh", fresh_row["status"] == "running",
                  f"got {fresh_row['status']}"))

    # ----- 7. tracking helper best-effort — 닫힌 conn 에 호출해도 raise 안 함 -----
    conn3 = _conn()
    conn3.close()
    try:
        rid3 = db.poll_run_start(conn3, run_label="x", pid=1, n_sites=1)
        ok_swallow = (rid3 is None)
    except Exception:
        ok_swallow = False
    cases.append(("tracking_swallows_db_error", ok_swallow, f"rid3={rid3 if 'rid3' in dir() else 'raised'}"))

    # ----- 8. notify_run round-trip + target finish -----
    conn4 = _conn()
    nrid = db.notify_run_start(conn4, pid=1, args_json='[]', now_hhmm='08:30',
                                today_kst='2026-05-25', n_due_targets=1)
    cases.append(("notify_run_start", nrid is not None, f"got {nrid}"))
    db.notify_target_run_finish(conn4, run_id=nrid, target_kind='dm', target_id='u1',
                                 started_at='2026-05-25T00:00:00+00:00',
                                 ended_at='2026-05-25T00:00:02+00:00',
                                 status='ok', n_posts=3, n_chunks=1, duration_ms=2000)
    db.notify_run_finish(conn4, nrid, n_targets_ok=1, n_targets_failed=0,
                          n_posts_delivered=3, n_empty_notices=0, duration_ms=3000)
    nrow = db.get_notify_run(conn4, nrid)
    targets = db.notify_target_runs_for(conn4, nrid)
    cases.append(("notify_run_done_with_target",
                  nrow["status"] == "done" and len(targets) == 1 and targets[0]["n_posts"] == 3,
                  f"got run={dict(nrow)} targets={[dict(t) for t in targets]}"))

    # ----- 9. CHECK constraint 거부 — 잘못된 status enum INSERT 실패 -----
    conn5 = _conn()
    rid5 = db.poll_run_start(conn5, run_label="x", pid=1, n_sites=1)
    bad_ok = True
    try:
        conn5.execute(
            "INSERT INTO poll_site_runs(run_id,slug,started_at,status) "
            "VALUES(?,?,?,?)",
            (rid5, "x", "2026-05-25T00:00:00+00:00", "wat_status"))
        conn5.commit()
    except sqlite3.IntegrityError:
        bad_ok = False
    cases.append(("status_check_constraint", not bad_ok, f"got bad_ok={bad_ok}"))

    # ----- 9b. 'error' status accepted (codex HIGH — _fetch_one 의 config 로드 실패 path) -----
    conn5b = _conn()
    rid5b = db.poll_run_start(conn5b, run_label="x", pid=1, n_sites=1)
    db.poll_site_run_finish(conn5b, run_id=rid5b, slug="bad",
                             started_at="2026-05-25T00:00:00+00:00",
                             ended_at="2026-05-25T00:00:01+00:00",
                             status="error", error_msg="config 파일 없음")
    err_row = conn5b.execute(
        "SELECT status, error_msg FROM poll_site_runs WHERE run_id=? AND slug='bad'",
        (rid5b,)).fetchone()
    cases.append(("error_status_accepted",
                  err_row is not None and err_row["status"] == "error",
                  f"got {dict(err_row) if err_row else None}"))

    # ----- 9c. 'skipped_test_target' status accepted (codex MED — dry-run path) -----
    conn5c = _conn()
    nrid5c = db.notify_run_start(conn5c, pid=1, n_due_targets=2)
    db.notify_target_run_finish(conn5c, run_id=nrid5c, target_kind='dm', target_id='owner',
                                 started_at='2026-05-25T00:00:00+00:00',
                                 ended_at='2026-05-25T00:00:01+00:00',
                                 status='ok', n_posts=3, n_chunks=1)
    db.notify_target_run_finish(conn5c, run_id=nrid5c, target_kind='channel', target_id='abc',
                                 started_at='2026-05-25T00:00:00+00:00',
                                 ended_at='2026-05-25T00:00:01+00:00',
                                 status='skipped_test_target', n_posts=0, n_chunks=0)
    targets_5c = db.notify_target_runs_for(conn5c, nrid5c)
    statuses_5c = sorted(t["status"] for t in targets_5c)
    cases.append(("skipped_test_target_status_accepted",
                  statuses_5c == ['ok', 'skipped_test_target'],
                  f"got {statuses_5c}"))

    # ----- 9d. notify reaper child sentinel — _unknown_ row 박음 (codex MED) -----
    conn5d = _conn()
    stale_notify = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    conn5d.execute(
        "INSERT INTO notify_runs(started_at,pid,host,n_due_targets,status) "
        "VALUES(?,?,?,?,?)", (stale_notify, 999999, "__fake_host__", 3, "running"))
    conn5d.commit()
    n5d = db.reap_stale_notify_runs(conn5d)
    cases.append(("notify_reaper_marks_stale", n5d >= 1, f"got {n5d}"))
    unk_n = conn5d.execute(
        "SELECT error_msg FROM notify_target_runs WHERE target_kind='_unknown_' AND status='run_crashed'"
    ).fetchone()
    cases.append(("notify_reaper_child_sentinel",
                  unk_n is not None and "missing_count=3" in (unk_n["error_msg"] or ""),
                  f"got {dict(unk_n) if unk_n else None}"))

    # ----- 9f. enum migration — 옛 CHECK 으로 만든 DB 에 connect 시 rebuild + 새 status 받음 -----
    # codex 2차 HIGH — CREATE TABLE IF NOT EXISTS 가 기존 CHECK 갱신 안 함 fix 검증.
    old_path = Path(tempfile.mkdtemp()) / "old.sqlite3"
    raw = sqlite3.connect(str(old_path))
    # 옛 enum (error 없음, skipped_test_target 없음) 으로 미리 박는다.
    # 실제 운영 시나리오 = 같은 컬럼, 옛 CHECK enum 만. CHECK 갱신 fix 검증이 목적.
    raw.executescript("""
        CREATE TABLE poll_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_label TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            reaped_at TEXT,
            reap_reason TEXT,
            pid INTEGER NOT NULL,
            host TEXT,
            git_sha TEXT,
            args_json TEXT,
            n_sites INTEGER,
            n_done INTEGER NOT NULL DEFAULT 0,
            n_timeout INTEGER NOT NULL DEFAULT 0,
            n_error INTEGER NOT NULL DEFAULT 0,
            n_lurking_skipped INTEGER NOT NULL DEFAULT 0,
            n_attempted_unique INTEGER NOT NULL DEFAULT 0,
            n_inserted INTEGER NOT NULL DEFAULT 0,
            n_present_after INTEGER NOT NULL DEFAULT 0,
            persist_mismatch_sites INTEGER NOT NULL DEFAULT 0,
            duration_ms INTEGER,
            status TEXT NOT NULL DEFAULT 'running'
                CHECK (status IN ('running','done','crashed','killed'))
        );
        CREATE TABLE poll_site_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES poll_runs(id),
            slug TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            status TEXT NOT NULL CHECK (status IN
                ('ok','lurking','breakage','poll_timeout','task_exception',
                 'persist_mismatch','body_empty_drift','reprobe_enqueued',
                 'reprobe_skipped_bug','reprobe_enqueue_failed','run_crashed')),
            n_posts INTEGER NOT NULL DEFAULT 0,
            n_new INTEGER NOT NULL DEFAULT 0,
            n_attempted_unique INTEGER NOT NULL DEFAULT 0,
            n_inserted INTEGER NOT NULL DEFAULT 0,
            n_present_after INTEGER NOT NULL DEFAULT 0,
            duration_ms INTEGER,
            error_msg TEXT,
            note TEXT,
            UNIQUE(run_id, slug)
        );
        CREATE TABLE notify_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            reaped_at TEXT,
            reap_reason TEXT,
            pid INTEGER NOT NULL,
            host TEXT,
            args_json TEXT,
            now_hhmm TEXT,
            today_kst TEXT,
            n_due_targets INTEGER NOT NULL DEFAULT 0,
            n_targets_ok INTEGER NOT NULL DEFAULT 0,
            n_targets_failed INTEGER NOT NULL DEFAULT 0,
            n_posts_delivered INTEGER NOT NULL DEFAULT 0,
            n_empty_notices INTEGER NOT NULL DEFAULT 0,
            duration_ms INTEGER,
            status TEXT NOT NULL DEFAULT 'running'
                CHECK (status IN ('running','done','crashed','killed'))
        );
        CREATE TABLE notify_target_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES notify_runs(id),
            target_kind TEXT NOT NULL,
            target_id TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            status TEXT NOT NULL CHECK (status IN
                ('ok','empty','no_subs','failed','exception','run_crashed')),
            n_posts INTEGER NOT NULL DEFAULT 0,
            n_chunks INTEGER NOT NULL DEFAULT 0,
            duration_ms INTEGER,
            error_msg TEXT,
            UNIQUE(run_id, target_kind, target_id)
        );
    """)
    raw.execute("INSERT INTO poll_runs(run_label,started_at,pid,n_sites,status) VALUES('legacy','2026-05-20T00:00:00+00:00',1,1,'done')")
    raw.execute("INSERT INTO poll_site_runs(run_id,slug,started_at,status) VALUES(1,'legacy_site','2026-05-20T00:00:00+00:00','ok')")
    raw.commit()
    raw.close()
    # 이제 db.connect() 가 마이그 — 'error' / 'skipped_test_target' enum 추가.
    conn_mig = db.connect(old_path)
    # 옛 row 유지
    legacy = conn_mig.execute("SELECT slug FROM poll_site_runs WHERE slug='legacy_site'").fetchone()
    cases.append(("migration_preserves_legacy_rows",
                  legacy is not None, f"got {dict(legacy) if legacy else None}"))
    # 새 enum 받아짐
    rid_m = db.poll_run_start(conn_mig, run_label="post_migration", pid=1, n_sites=1)
    db.poll_site_run_finish(conn_mig, run_id=rid_m, slug="x",
                             started_at="2026-05-25T00:00:00+00:00",
                             ended_at="2026-05-25T00:00:01+00:00",
                             status="error", error_msg="post-migration test")
    err_after = conn_mig.execute(
        "SELECT status FROM poll_site_runs WHERE slug='x'").fetchone()
    cases.append(("migration_accepts_new_error_status",
                  err_after is not None and err_after["status"] == "error",
                  f"got {dict(err_after) if err_after else None}"))
    nrid_m = db.notify_run_start(conn_mig, pid=1, n_due_targets=1)
    db.notify_target_run_finish(conn_mig, run_id=nrid_m, target_kind='dm', target_id='x',
                                 started_at='2026-05-25T00:00:00+00:00',
                                 ended_at='2026-05-25T00:00:01+00:00',
                                 status='skipped_test_target', n_posts=0, n_chunks=0)
    skip_after = conn_mig.execute(
        "SELECT status FROM notify_target_runs WHERE target_id='x'").fetchone()
    cases.append(("migration_accepts_new_skipped_status",
                  skip_after is not None and skip_after["status"] == "skipped_test_target",
                  f"got {dict(skip_after) if skip_after else None}"))
    conn_mig.close()

    # ----- 9e. reap_stale_* swallows closed-DB error (codex MED — best-effort guard) -----
    conn5e = _conn()
    conn5e.close()
    try:
        n_p = db.reap_stale_poll_runs(conn5e)
        n_n = db.reap_stale_notify_runs(conn5e)
        ok_reap_swallow = n_p == 0 and n_n == 0
    except Exception:
        ok_reap_swallow = False
    cases.append(("reaper_swallows_closed_db", ok_reap_swallow,
                  f"got n_p={n_p if 'n_p' in dir() else 'raised'}"))

    # ----- 10. prune_runs — 90d/30d 보존 -----
    conn6 = _conn()
    old = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    new = datetime.now(timezone.utc).isoformat()
    conn6.execute(
        "INSERT INTO poll_runs(run_label,started_at,pid,n_sites,status) "
        "VALUES('old', ?, 1, 1, 'done')", (old,))
    conn6.execute(
        "INSERT INTO poll_runs(run_label,started_at,pid,n_sites,status) "
        "VALUES('new', ?, 1, 1, 'done')", (new,))
    conn6.commit()
    out = db.prune_runs(conn6)
    remaining = [r[0] for r in conn6.execute("SELECT run_label FROM poll_runs").fetchall()]
    cases.append(("prune_runs_drops_old",
                  out["poll_runs"] >= 1 and "old" not in remaining and "new" in remaining,
                  f"out={out} remaining={remaining}"))

    return cases


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    results = run()
    failed = [(n, d) for n, ok, d in results if not ok]
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {d}")
    if failed:
        print(f"\n{len(failed)} FAILED")
        sys.exit(1)
    print(f"\n{len(results)} passed")
