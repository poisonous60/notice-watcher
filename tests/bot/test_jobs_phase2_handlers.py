"""ADR 0019 Phase 2b/c/d/e/h — worker handlers + freshness barrier tests."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _conn() -> sqlite3.Connection:
    from bot import db
    p = Path(tempfile.mkdtemp(prefix="jobs_phase2_")) / "bot.sqlite3"
    return db.connect(p)


def _job(conn: sqlite3.Connection, job_id: int):
    return conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def _seed_due_target(conn: sqlite3.Connection, *, target_kind: str = "dm",
                     target_id: str = "u1", today: str = "2026-05-25") -> None:
    from bot import db
    conn.execute(
        "INSERT INTO subscriptions(user_id,slug,url,filter_prompt,schedule,target_kind,target_id,notify_empty,created_at) "
        "VALUES(?,?,?,?,?,?,?,0,?)",
        (target_id, "site1", "https://example.com/notice", None, "realtime",
         target_kind, target_id, "2000-01-01T00:00:00+00:00"),
    )
    db.ensure_setting(conn, target_kind=target_kind, target_id=target_id)
    conn.execute(
        "UPDATE user_settings SET deliver_at='08:30', last_delivered_date=NULL "
        "WHERE user_id=?",
        (target_id,),
    )
    conn.commit()


def _test_claim_skips_future_requeue_at() -> tuple[str, bool, str]:
    """pending deliver_target with future requeue_at is not claimable until due."""
    from bot import db
    conn = _conn()
    jid, _ = db.enqueue_job(
        conn,
        kind="deliver_target",
        dedupe_key="deliver:dm:u1:2026-05-25",
        sub_payload=json.dumps({"target_kind": "dm", "target_id": "u1", "today_kst": "2026-05-25"}),
    )
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    conn.execute("UPDATE jobs SET requeue_at=? WHERE id=?", (future, jid))
    conn.commit()
    claimed = db.claim_next_pending(conn)
    return (
        "claim_skips_future_requeue_at",
        claimed is None,
        f"claimed={dict(claimed) if claimed else None}",
    )


def _test_poll_run_barrier_and_finalize() -> tuple[str, bool, str]:
    """enqueue_done blocks delivery until all expected child poll_site_runs are terminal."""
    from bot import db
    conn = _conn()
    rid = db.poll_run_start(conn, run_label="20260525_pid1", pid=1,
                            n_sites=2, args_json=json.dumps(["--x"]))
    today = datetime.now(db.KST).strftime("%Y-%m-%d")
    db.poll_run_mark_enqueue_done(conn, rid)
    blocking, br_id, reason = db.poll_run_blocking_for_today(conn, today)
    if not (blocking and br_id == rid and reason == "enqueue_done_with_pending_children"):
        return ("poll_run_barrier_finalize", False,
                f"expected enqueue_done barrier, got {(blocking, br_id, reason)}")
    for slug in ("a", "b"):
        db.poll_site_run_finish(
            conn, run_id=rid, slug=slug,
            started_at="2026-05-25T00:00:00+00:00",
            ended_at="2026-05-25T00:00:01+00:00",
            status="ok",
        )
    changed = db.poll_run_maybe_finalize(conn, rid)
    row = db.get_poll_run(conn, rid)
    blocking2, _, reason2 = db.poll_run_blocking_for_today(conn, today)
    return (
        "poll_run_barrier_finalize",
        changed and row["status"] == "done" and not blocking2 and reason2 is None,
        f"changed={changed} row={dict(row)} barrier2={(blocking2, reason2)}",
    )


def _test_deliver_target_requeues_on_poll_barrier() -> tuple[str, bool, str]:
    """worker deliver_target handler returns job to pending with requeue_at while poll is active."""
    from bot import db
    from bot import worker
    conn = _conn()
    today = datetime.now(db.KST).strftime("%Y-%m-%d")
    rid = db.poll_run_start(conn, run_label="active", pid=1, n_sites=1)
    jid, _ = db.enqueue_job(
        conn,
        kind="deliver_target",
        dedupe_key=f"deliver:dm:u1:{today}",
        sub_payload=json.dumps({"target_kind": "dm", "target_id": "u1", "today_kst": today}),
    )
    job = db.claim_next_pending(conn)
    try:
        asyncio.run(worker._process_deliver_target(None, conn, job))
    except Exception as e:  # noqa: BLE001
        return ("deliver_target_barrier_requeue", False, f"raised {type(e).__name__}: {e!r} run_id={rid}")
    row = _job(conn, jid)
    return (
        "deliver_target_barrier_requeue",
        row["status"] == "pending" and row["requeue_at"],
        f"job={dict(row)}",
    )


def _test_delivery_tick_enqueue_idempotent() -> tuple[str, bool, str]:
    """delivery tick enqueues one deliver_target per due target/day and dedupe skips repeats."""
    from bot import delivery_tick
    conn = _conn()
    _seed_due_target(conn)
    n1 = delivery_tick._enqueue_due_targets(conn, now_hhmm="08:30", today_kst="2026-05-25")
    n2 = delivery_tick._enqueue_due_targets(conn, now_hhmm="08:31", today_kst="2026-05-25")
    rows = conn.execute("SELECT kind, dedupe_key, sub_payload FROM jobs WHERE kind='deliver_target'").fetchall()
    payload = json.loads(rows[0]["sub_payload"]) if rows else {}
    return (
        "delivery_tick_enqueue_idempotent",
        n1 == 1 and n2 == 0 and len(rows) == 1
        and rows[0]["dedupe_key"] == "deliver:dm:u1:2026-05-25"
        and payload == {"target_kind": "dm", "target_id": "u1", "today_kst": "2026-05-25"},
        f"n1={n1} n2={n2} rows={[dict(r) for r in rows]}",
    )


def _test_worker_dispatches_poll_site_kind() -> tuple[str, bool, str]:
    """_process_job_inner dispatches poll_site to the poll_site handler, not register/reprobe guards."""
    from bot import db
    from bot import worker
    conn = _conn()
    jid, _ = db.enqueue_job(
        conn,
        kind="poll_site",
        url="https://example.com/notice",
        slug="site1",
        dedupe_key="poll:1:site1",
        sub_payload=json.dumps({"run_id": 1, "slug": "site1", "state_path": "unused.json"}),
    )
    job = db.claim_next_pending(conn)
    calls: list[int] = []
    orig = getattr(worker, "_process_poll_site", None)

    async def fake_process_poll_site(conn_arg, job_arg):
        calls.append(int(job_arg["id"]))
        db.mark_job_finished(conn_arg, int(job_arg["id"]), ok=True, rc=0, tail="fake poll_site")

    worker._process_poll_site = fake_process_poll_site
    try:
        asyncio.run(worker._process_job_inner(None, conn, job, None))
    finally:
        if orig is None:
            delattr(worker, "_process_poll_site")
        else:
            worker._process_poll_site = orig
    row = _job(conn, jid)
    return (
        "worker_dispatches_poll_site_kind",
        calls == [jid] and row["status"] == "done" and row["result_tail"] == "fake poll_site",
        f"calls={calls} job={dict(row)}",
    )


def _test_poll_chromium_site_enqueues_poll_site_job() -> tuple[str, bool, str]:
    """scripts.poll routes chromium configs to poll_site jobs instead of inline fetch."""
    from bot import db
    from scripts import poll
    conn = _conn()
    tmp = Path(tempfile.mkdtemp(prefix="poll_enqueue_"))
    cfg = tmp / "site.json"
    state_path = tmp / "state.json"
    cfg.write_text(json.dumps({"strategy": "playwright_html"}, ensure_ascii=False), encoding="utf-8")
    state = {
        "slug": "site1",
        "url": "https://example.com/notice",
        "config_path": str(cfg),
        "_state_path": str(state_path),
    }
    state_path.write_text(json.dumps({k: v for k, v in state.items() if k != "_state_path"}), encoding="utf-8")

    async def go():
        return await poll._site_with_timeout(
            state,
            timeout=1.0,
            sem_chromium=asyncio.Semaphore(1),
            sem_httpx=asyncio.Semaphore(1),
            run_id=123,
            db_conn=conn,
            db_lock=asyncio.Lock(),
            page_size=7,
            max_new_articles=3,
            lurking=False,
            no_reprobe=True,
            run_dir=tmp / "run",
        )

    lines, row, tracking = asyncio.run(go())
    jobs = conn.execute("SELECT kind, slug, url, dedupe_key, sub_payload FROM jobs").fetchall()
    payload = json.loads(jobs[0]["sub_payload"]) if jobs else {}
    return (
        "poll_chromium_site_enqueues_poll_site_job",
        row[1] == "enqueued"
        and tracking["status"] == "enqueued"
        and len(jobs) == 1
        and jobs[0]["kind"] == "poll_site"
        and jobs[0]["dedupe_key"] == "poll:123:site1"
        and payload["state_path"] == str(state_path)
        and payload["page_size"] == 7
        and "enqueued" in lines[0],
        f"row={row} tracking={tracking} jobs={[dict(j) for j in jobs]} payload={payload}",
    )


def run() -> list[tuple[str, bool, str]]:
    return [
        _test_claim_skips_future_requeue_at(),
        _test_poll_run_barrier_and_finalize(),
        _test_deliver_target_requeues_on_poll_barrier(),
        _test_delivery_tick_enqueue_idempotent(),
        _test_worker_dispatches_poll_site_kind(),
        _test_poll_chromium_site_enqueues_poll_site_job(),
    ]


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
