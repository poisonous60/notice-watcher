"""bot.db — ADR 0006 발송 시각 설정 + posts 캐시 + due 쿼리 단위 테스트.

codex 리뷰가 짚은 정확성 지점 위주: 신규 구독자 백로그 차단(created_at 하한), due 경계
(deliver_at <= now AND last_delivered_date < today), prune 미수신 가드. discord/LLM 안 띄움.
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


def _post(pid: str, **kw) -> dict:
    d = {"post_id": pid, "title": f"T{pid}", "url": f"http://x/{pid}",
         "published_at": "2026-05-20", "category": None, "content_html": "<p>body</p>"}
    d.update(kw)
    return d


def run() -> list[tuple[str, bool, str]]:
    from bot import db
    cases: list[tuple[str, bool, str]] = []

    # ----- 1. ensure_setting 기본값 08:30 -----
    conn = _conn()
    db.ensure_setting(conn, target_kind="dm", target_id="u1")
    cases.append(("default_deliver_at_0830",
                  db.get_deliver_at(conn, target_kind="dm", target_id="u1") == "08:30",
                  f"got {db.get_deliver_at(conn, target_kind='dm', target_id='u1')!r}"))

    # ----- 2. set_deliver_at round-trip + ensure 가 기존값 안 덮음 -----
    db.set_deliver_at(conn, target_kind="dm", target_id="u1", deliver_at="09:15")
    db.ensure_setting(conn, target_kind="dm", target_id="u1")  # INSERT OR IGNORE — 안 건드림
    cases.append(("set_deliver_at_then_ensure_keeps",
                  db.get_deliver_at(conn, target_kind="dm", target_id="u1") == "09:15",
                  f"got {db.get_deliver_at(conn, target_kind='dm', target_id='u1')!r}"))

    # ----- 3. due 경계: deliver_at <= now, last_delivered_date < today -----
    due_before = db.due_targets(conn, now_hhmm="09:00", today_kst="2026-05-20")
    due_at = db.due_targets(conn, now_hhmm="09:15", today_kst="2026-05-20")
    due_after = db.due_targets(conn, now_hhmm="23:59", today_kst="2026-05-20")
    cases.append(("due_not_before_time", due_before == [], f"got {due_before!r}"))
    cases.append(("due_at_time", len(due_at) == 1 and due_at[0]["target_id"] == "u1", f"got {due_at!r}"))
    cases.append(("due_catchup_after_time", len(due_after) == 1, f"got {due_after!r}"))

    # ----- 4. mark 후 같은 날 안 잡힘, 다음 날 다시 잡힘 (멱등 + catch-up) -----
    db.mark_setting_delivered(conn, target_kind="dm", target_id="u1", today_kst="2026-05-20")
    same = db.due_targets(conn, now_hhmm="23:59", today_kst="2026-05-20")
    nxt = db.due_targets(conn, now_hhmm="09:15", today_kst="2026-05-21")
    cases.append(("due_idempotent_same_day", same == [], f"got {same!r}"))
    cases.append(("due_again_next_day", len(nxt) == 1, f"got {nxt!r}"))

    # ----- 5. 채널 설정은 별 테이블 — 같은 id 라도 분리 -----
    conn2 = _conn()
    db.set_deliver_at(conn2, target_kind="channel", target_id="c1", deliver_at="20:00")
    chan_due = db.due_targets(conn2, now_hhmm="20:00", today_kst="2026-05-20")
    cases.append(("channel_setting_due",
                  len(chan_due) == 1 and chan_due[0]["target_kind"] == "channel",
                  f"got {chan_due!r}"))

    # ----- 6. posts upsert + INSERT OR IGNORE 가 summary 캐시 안 날림 -----
    conn3 = _conn()
    db.upsert_post(conn3, "s1", _post("p1"))
    db.set_post_summary(conn3, "s1", "p1", "cached summary")
    db.upsert_post(conn3, "s1", _post("p1", title="CHANGED"))  # 재폴링 — IGNORE
    rows = db.posts_for_slug_since(conn3, "s1", "2000-01-01")
    keep = rows[0]["summary"] == "cached summary" and rows[0]["title"] == "T p1".replace(" ", "")
    cases.append(("upsert_ignore_keeps_summary",
                  rows[0]["summary"] == "cached summary",
                  f"got summary={rows[0]['summary']!r} title={rows[0]['title']!r}"))

    # ----- 7. CRITICAL — 백로그 차단: 구독 created_at 이후 글만 빚짐 -----
    # subscription.created_at 은 _now_iso() (UTC). 그보다 과거 collected_at 의 글은 안 owed.
    conn4 = _conn()
    # 과거 글 먼저 박고(collected_at = now), 그 다음 구독 생성 → since(now) > 그 글 collected_at?
    # upsert 가 collected_at=now 라, 구독 created_at 이 그 *후* 면 since>collected → 제외.
    old_post_t = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    conn4.execute(
        "INSERT INTO posts(slug,post_id,title,url,published_at,category,content_html,summary,collected_at) "
        "VALUES('s1','old','T','u','2026-05-18',NULL,'<p>x</p>',NULL,?)", (old_post_t,))
    conn4.commit()
    sub_created = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    conn4.execute(
        "INSERT INTO subscriptions(user_id,slug,url,filter_prompt,schedule,target_kind,target_id,notify_empty,created_at) "
        "VALUES('u1','s1','u',NULL,'realtime','dm','u1',0,?)", (sub_created,))
    conn4.commit()
    # 새 글(now) 도 박음 — 이건 owed 여야.
    db.upsert_post(conn4, "s1", _post("new"))
    owed = db.posts_for_slug_since(conn4, "s1", sub_created)
    owed_ids = {r["post_id"] for r in owed}
    cases.append(("backlog_bound_excludes_pre_subscription",
                  "old" not in owed_ids and "new" in owed_ids,
                  f"owed={owed_ids!r}"))

    # ----- 8. prune 미수신 가드: 안 받은 구독 대상 있으면 보존, 받았으면 삭제 -----
    conn5 = _conn()
    old_t = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    conn5.execute(
        "INSERT INTO posts(slug,post_id,title,url,published_at,category,content_html,summary,collected_at) "
        "VALUES('s1','pold','T','u','2026-04-01',NULL,'<p>x</p>',NULL,?)", (old_t,))
    conn5.execute(
        "INSERT INTO subscriptions(user_id,slug,url,filter_prompt,schedule,target_kind,target_id,notify_empty,created_at) "
        "VALUES('u1','s1','u',NULL,'realtime','dm','u1',0,?)", (old_t,))
    conn5.commit()
    pruned_guarded = db.prune_posts(conn5, keep_days=7)  # 미수신 → 보존
    db.mark_delivered(conn5, "s1", "pold", "u1")
    pruned_after = db.prune_posts(conn5, keep_days=7)  # 수신 완료 → 삭제
    cases.append(("prune_keeps_undelivered", pruned_guarded == 0, f"pruned={pruned_guarded}"))
    cases.append(("prune_deletes_after_delivered", pruned_after == 1, f"pruned={pruned_after}"))

    # ----- 9. flush_target — 채널 OR 필터 + 1회 발송 + mark (LLM/Discord stub) -----
    import scripts.deliver_due as dd
    sent: list[tuple] = []
    orig = (dd.summarize_post, dd.filter_pass, dd.deliver, dd.client_for)
    dd.summarize_post = lambda c, p, slug=None: "stub-summary"
    # filter_A 는 항상 reject, filter_B 는 항상 pass → OR 이면 통과해야.
    dd.filter_pass = lambda c, fp, p, s, slug=None: (fp == "B")
    dd.deliver = lambda tok, target_kind, target_id, content: sent.append((target_kind, target_id, content))
    dd.client_for = lambda site: None
    try:
        conn6 = _conn()
        # 같은 채널 c1 에 두 구독자, slug s1, 필터 A(거부)/B(통과)
        for uid, fp in (("uA", "A"), ("uB", "B")):
            conn6.execute(
                "INSERT INTO subscriptions(user_id,slug,url,filter_prompt,schedule,target_kind,target_id,notify_empty,created_at) "
                "VALUES(?,?,?,?,'realtime','channel','c1',0,'2000-01-01T00:00:00+00:00')",
                (uid, "s1", "u", fp))
        conn6.commit()
        db.upsert_post(conn6, "s1", _post("p1"))
        n = dd.flush_target(conn6, "tok", {"target_kind": "channel", "target_id": "c1"},
                            today_kst="2026-05-20", dry_run=False)
        delivered = db.was_delivered(conn6, "s1", "p1", "c1")
        marked = db.due_targets(conn6, now_hhmm="23:59", today_kst="2026-05-20")  # 멱등 — 이제 안 잡힘? c1 설정 행 없음
        cases.append(("flush_or_filter_delivers_once",
                      n == 1 and len(sent) == 1 and delivered,
                      f"n={n} sent={len(sent)} delivered={delivered}"))

        # ----- 10. notify_empty — 빚진 글 0 인데 notify_empty 구독이면 빈 메시지 -----
        sent.clear()
        conn7 = _conn()
        conn7.execute(
            "INSERT INTO subscriptions(user_id,slug,url,filter_prompt,schedule,target_kind,target_id,notify_empty,created_at) "
            "VALUES('u1','s1','u',NULL,'realtime','dm','u1',1,'2000-01-01T00:00:00+00:00')")
        db.ensure_setting(conn7, target_kind="dm", target_id="u1")
        conn7.commit()
        n2 = dd.flush_target(conn7, "tok", {"target_kind": "dm", "target_id": "u1"},
                             today_kst="2026-05-20", dry_run=False)
        cases.append(("flush_notify_empty_sends_line",
                      n2 == 0 and len(sent) == 1 and "없어요" in sent[0][2],
                      f"n={n2} sent={sent!r}"))
    finally:
        dd.summarize_post, dd.filter_pass, dd.deliver, dd.client_for = orig

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
