"""bot.db — announce_prefs / announcements 헬퍼 + recipient 계산 단위 테스트.

DM/채널 옵트아웃이 발송 대상 목록에서 제대로 제외되는지 본다. 다른 테스트와 동일하게
임시 SQLite 파일 + run() 컨벤션. discord 게이트웨이는 안 띄움.
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path


def _setup_conn() -> sqlite3.Connection:
    from bot import db
    p = Path(tempfile.mkdtemp()) / "t.sqlite3"
    return db.connect(p)


def run() -> list[tuple[str, bool, str]]:
    from bot import db
    cases: list[tuple[str, bool, str]] = []

    # ----- 1. default opt-in — 아무 row 없을 때 get_announce_optout=False -----
    conn = _setup_conn()
    cases.append((
        "default_opt_in_dm",
        db.get_announce_optout(conn, "dm", "u_any") is False,
        f"got {db.get_announce_optout(conn, 'dm', 'u_any')!r}",
    ))
    cases.append((
        "default_opt_in_channel",
        db.get_announce_optout(conn, "channel", "c_any") is False,
        f"got {db.get_announce_optout(conn, 'channel', 'c_any')!r}",
    ))

    # ----- 2. set / unset opt-out — round-trip -----
    db.set_announce_optout(conn, "dm", "u1", opted_out=True)
    cases.append((
        "set_optout_true",
        db.get_announce_optout(conn, "dm", "u1") is True,
        f"got {db.get_announce_optout(conn, 'dm', 'u1')!r}",
    ))
    db.set_announce_optout(conn, "dm", "u1", opted_out=False)
    cases.append((
        "set_optout_false_after_true",
        db.get_announce_optout(conn, "dm", "u1") is False,
        f"got {db.get_announce_optout(conn, 'dm', 'u1')!r}",
    ))

    # ----- 3. invalid scope_kind 거부 -----
    try:
        db.get_announce_optout(conn, "bogus", "x")
        cases.append(("invalid_scope_rejected", False, "no ValueError"))
    except ValueError:
        cases.append(("invalid_scope_rejected", True, "ValueError raised"))

    # ----- 4. recipient — subscriptions 있어야 대상 — 없으면 빈 목록 -----
    conn2 = _setup_conn()
    cases.append((
        "no_subs_no_recipients_dm",
        db.announce_recipients_dm(conn2) == [],
        f"got {db.announce_recipients_dm(conn2)!r}",
    ))
    cases.append((
        "no_subs_no_recipients_channel",
        db.announce_recipients_channel(conn2) == [],
        f"got {db.announce_recipients_channel(conn2)!r}",
    ))

    # ----- 5. DM recipient — distinct user_id, 옵트아웃 제외 -----
    conn3 = _setup_conn()
    db.add_subscription(conn3, user_id="userA", slug="s1", url="https://x", filter_prompt=None,
                        schedule="realtime", target_kind="dm", target_id="userA")
    db.add_subscription(conn3, user_id="userA", slug="s2", url="https://y", filter_prompt=None,
                        schedule="realtime", target_kind="dm", target_id="userA")  # 같은 user 2 sub → 1번만
    db.add_subscription(conn3, user_id="userB", slug="s1", url="https://x", filter_prompt=None,
                        schedule="realtime", target_kind="channel", target_id="chan1")  # 채널 구독자 → DM 대상에도 들어감
    got = sorted(db.announce_recipients_dm(conn3))
    cases.append((
        "dm_recipients_distinct",
        got == ["userA", "userB"],
        f"got {got!r}",
    ))

    db.set_announce_optout(conn3, "dm", "userA", opted_out=True)
    got = sorted(db.announce_recipients_dm(conn3))
    cases.append((
        "dm_recipients_excludes_optout",
        got == ["userB"],
        f"got {got!r}",
    ))

    # 옵트인 복귀 → 다시 포함
    db.set_announce_optout(conn3, "dm", "userA", opted_out=False)
    got = sorted(db.announce_recipients_dm(conn3))
    cases.append((
        "dm_recipients_reincludes_after_optin",
        got == ["userA", "userB"],
        f"got {got!r}",
    ))

    # ----- 6. Channel recipient — target_kind='channel' 만, distinct target_id -----
    conn4 = _setup_conn()
    db.add_subscription(conn4, user_id="userA", slug="s1", url="https://x", filter_prompt=None,
                        schedule="realtime", target_kind="dm", target_id="userA")  # DM → 채널 대상 아님
    db.add_subscription(conn4, user_id="userB", slug="s1", url="https://x", filter_prompt=None,
                        schedule="realtime", target_kind="channel", target_id="chan1")
    db.add_subscription(conn4, user_id="userC", slug="s1", url="https://x", filter_prompt=None,
                        schedule="realtime", target_kind="channel", target_id="chan1")  # 같은 채널 다른 user → 1번만
    db.add_subscription(conn4, user_id="userB", slug="s2", url="https://y", filter_prompt=None,
                        schedule="realtime", target_kind="channel", target_id="chan2")
    got = sorted(db.announce_recipients_channel(conn4))
    cases.append((
        "channel_recipients_distinct_excludes_dm",
        got == ["chan1", "chan2"],
        f"got {got!r}",
    ))

    db.set_announce_optout(conn4, "channel", "chan2", opted_out=True)
    got = sorted(db.announce_recipients_channel(conn4))
    cases.append((
        "channel_recipients_excludes_optout",
        got == ["chan1"],
        f"got {got!r}",
    ))

    # 채널 옵트아웃은 DM recipient 에 영향 없음(scope_kind 별 격리)
    got = sorted(db.announce_recipients_dm(conn4))
    cases.append((
        "channel_optout_isolated_from_dm",
        got == ["userA", "userB", "userC"],
        f"got {got!r}",
    ))

    # ----- 7. announcements — add + count update + recent -----
    conn5 = _setup_conn()
    aid = db.add_announcement(conn5, title="t1", message="hello", sent_by="owner1")
    cases.append((
        "add_announcement_returns_id",
        isinstance(aid, int) and aid > 0,
        f"got {aid!r}",
    ))
    db.update_announcement_counts(conn5, aid, dm_sent=5, dm_failed=1,
                                  channel_sent=2, channel_failed=0)
    rows = db.recent_announcements(conn5)
    r = dict(rows[0])
    ok = (r["title"] == "t1" and r["message"] == "hello" and r["sent_by"] == "owner1"
          and r["dm_sent"] == 5 and r["dm_failed"] == 1
          and r["channel_sent"] == 2 and r["channel_failed"] == 0)
    cases.append((
        "announcement_counts_persisted",
        ok,
        f"got {r!r}",
    ))

    # 재발송 dedup 안 함 — 같은 title/message 다시 add → 새 id
    aid2 = db.add_announcement(conn5, title="t1", message="hello", sent_by="owner1")
    cases.append((
        "announcement_no_dedup",
        aid2 != aid and aid2 > aid,
        f"got aid={aid} aid2={aid2}",
    ))

    # ----- 8. feedback — add + recent ordering -----
    conn6 = _setup_conn()
    f1 = db.add_feedback(conn6, user_id="u1", username="alice#001", message="first")
    f2 = db.add_feedback(conn6, user_id="u2", username="bob#002", message="second\nwith newline")
    rows = db.list_feedback(conn6)
    cases.append((
        "feedback_recent_desc",
        len(rows) == 2 and rows[0]["id"] == f2 and rows[1]["id"] == f1,
        f"got ids={[r['id'] for r in rows]!r}",
    ))
    cases.append((
        "feedback_fields_persisted",
        rows[0]["user_id"] == "u2" and rows[0]["username"] == "bob#002"
        and rows[0]["message"] == "second\nwith newline",
        f"got {dict(rows[0])!r}",
    ))

    # limit honored
    f3 = db.add_feedback(conn6, user_id="u3", username="carol#003", message="third")
    rows = db.list_feedback(conn6, limit=2)
    cases.append((
        "feedback_limit_honored",
        len(rows) == 2 and rows[0]["id"] == f3,
        f"got n={len(rows)} ids={[r['id'] for r in rows]!r}",
    ))

    return cases


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    results = run()
    failed = [(n, d) for n, ok, d in results if not ok]
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {d}")
    if failed:
        print(f"\n{len(failed)} FAILED")
        sys.exit(1)
    print(f"\n{len(results)} passed")
