"""bot.inspector.diagnose — 휴리스틱 진단 룰. mock DB row + temp config/state JSON.

각 케이스: 특정 깨짐 신호를 가진 입력을 만들고 그 태그가 findings 에 들어왔는지 본다.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _setup_conn() -> sqlite3.Connection:
    from bot import db
    # in-memory DB — 매 케이스 새로
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(db._SCHEMA)
    return conn


def run() -> list[tuple[str, bool, str]]:
    from bot import inspector
    cases: list[tuple[str, bool, str]] = []
    now = datetime.now(timezone.utc)

    with tempfile.TemporaryDirectory() as td:
        paths = inspector.InspectorPaths(
            db_path=Path(td) / "_unused.sqlite3",
            configs_dir=Path(td) / "configs",
            state_dir=Path(td) / "state",
        )
        paths.configs_dir.mkdir()
        paths.state_dir.mkdir()

        # ------------------------------------------------------------------ #
        # 1) FAILED 마커 → auto_register_failed (error)
        slug = "fail.example.com_board"
        (paths.state_dir / f"{slug}.FAILED.json").write_text(
            json.dumps({"slug": slug, "reason": "테스트 사유"}), encoding="utf-8")
        conn = _setup_conn()
        findings = inspector.diagnose(
            conn, paths, slug=slug, subscriptions=[], latest_job=None,
            config=None, state=inspector._state_for(slug, paths))
        tags = {f.tag for f in findings}
        cases.append(("auto_register_failed", "auto_register_failed" in tags, f"tags={tags}"))

        # 2) config 없음 → config_missing (error)
        slug2 = "nope.example.com_x"
        conn = _setup_conn()
        findings = inspector.diagnose(
            conn, paths, slug=slug2, subscriptions=[], latest_job=None,
            config=None, state=None)
        tags = {f.tag for f in findings}
        cases.append(("config_missing", "config_missing" in tags, f"tags={tags}"))

        # 3) URL 에 query 있는데 config.kwargs 가 비어있음 → query_kwargs_mismatch
        slug3 = "arca.live_b_x_category_y"
        sub = {"user_id": "u1", "slug": slug3, "url": "https://arca.live/b/x?category=y",
               "target_id": "u1", "target_kind": "dm", "created_at": _iso(now), "filter_prompt": None,
               "notify_empty": 0}
        cfg = {"version": 1, "site": "arca.live", "board": "x", "kwargs": {}}
        conn = _setup_conn()
        findings = inspector.diagnose(
            conn, paths, slug=slug3, subscriptions=[sub], latest_job=None,
            config=cfg, state=None)
        tags = {f.tag for f in findings}
        cases.append(("query_kwargs_mismatch", "query_kwargs_mismatch" in tags, f"tags={tags}"))

        # 4) consecutive_breakage > 0 → breakage_signal
        slug4 = "breakage.example.com_x"
        state4 = {"ok": {"slug": slug4, "consecutive_breakage": 3, "last_poll_at": _iso(now),
                          "n_baseline": 10}, "failed": None}
        conn = _setup_conn()
        findings = inspector.diagnose(
            conn, paths, slug=slug4, subscriptions=[], latest_job=None,
            config={"kwargs": {}}, state=state4)
        tags = {f.tag for f in findings}
        cases.append(("breakage_signal", "breakage_signal" in tags, f"tags={tags}"))

        # 5) last_poll_at > 24h → stale_poll
        slug5 = "stale.example.com_x"
        state5 = {"ok": {"slug": slug5, "consecutive_breakage": 0,
                          "last_poll_at": _iso(now - timedelta(days=2)), "n_baseline": 5},
                  "failed": None}
        conn = _setup_conn()
        findings = inspector.diagnose(
            conn, paths, slug=slug5, subscriptions=[], latest_job=None,
            config={"kwargs": {}}, state=state5)
        tags = {f.tag for f in findings}
        cases.append(("stale_poll", "stale_poll" in tags, f"tags={tags}"))

        # 6) baseline=0 → empty_baseline
        slug6 = "empty.example.com_x"
        state6 = {"ok": {"slug": slug6, "consecutive_breakage": 0,
                          "last_poll_at": _iso(now), "n_baseline": 0}, "failed": None}
        conn = _setup_conn()
        findings = inspector.diagnose(
            conn, paths, slug=slug6, subscriptions=[], latest_job=None,
            config={"kwargs": {}}, state=state6)
        tags = {f.tag for f in findings}
        cases.append(("empty_baseline", "empty_baseline" in tags, f"tags={tags}"))

        # 7) never_delivered — 구독 8일 전, deliveries 0건, target_id 로 조회
        slug7 = "neverdeliver.example.com_x"
        old_sub = {"user_id": "u1", "slug": slug7,
                   "url": "https://neverdeliver.example.com/x",
                   "target_id": "channel_42", "target_kind": "channel",
                   "created_at": _iso(now - timedelta(days=8)),
                   "filter_prompt": None, "notify_empty": 0}
        conn = _setup_conn()
        # deliveries 비워둠
        findings = inspector.diagnose(
            conn, paths, slug=slug7, subscriptions=[old_sub], latest_job=None,
            config={"kwargs": {}}, state=None)
        tags = {f.tag for f in findings}
        cases.append(("never_delivered_old_sub", "never_delivered" in tags, f"tags={tags}"))

        # 7b) deliveries 가 있으면 never_delivered 안 뜸
        conn = _setup_conn()
        conn.execute("INSERT INTO deliveries VALUES (?,?,?,?)",
                     (slug7, "post_1", "channel_42", _iso(now)))
        conn.commit()
        findings = inspector.diagnose(
            conn, paths, slug=slug7, subscriptions=[old_sub], latest_job=None,
            config={"kwargs": {}}, state=None)
        tags = {f.tag for f in findings}
        cases.append(("never_delivered_suppressed_when_delivered",
                      "never_delivered" not in tags, f"tags={tags}"))

        # 7c) 구독 < 7일 → never_delivered 안 뜸 (오래된 거 아닌 새 구독엔 잡지 않음)
        slug7c = "new.example.com_x"
        new_sub = {**old_sub, "slug": slug7c, "created_at": _iso(now - timedelta(days=2)),
                   "target_id": "channel_43"}
        conn = _setup_conn()
        findings = inspector.diagnose(
            conn, paths, slug=slug7c, subscriptions=[new_sub], latest_job=None,
            config={"kwargs": {}}, state=None)
        tags = {f.tag for f in findings}
        cases.append(("never_delivered_skipped_new_sub", "never_delivered" not in tags, f"tags={tags}"))

        # 8) fetch_sim 빈 결과 → fetch_sim_empty
        slug8 = "fetch.example.com_x"
        conn = _setup_conn()
        findings = inspector.diagnose(
            conn, paths, slug=slug8, subscriptions=[], latest_job=None,
            config={"kwargs": {}}, state=None, fetch_sample=[])
        tags = {f.tag for f in findings}
        cases.append(("fetch_sim_empty", "fetch_sim_empty" in tags, f"tags={tags}"))

        # 9) fetch_sim 같은 post_id 만 → fetch_sim_same_id
        same = [{"post_id": "X", "title": "a", "url": "u1"},
                {"post_id": "X", "title": "b", "url": "u2"}]
        conn = _setup_conn()
        findings = inspector.diagnose(
            conn, paths, slug=slug8, subscriptions=[], latest_job=None,
            config={"kwargs": {}}, state=None, fetch_sample=same)
        tags = {f.tag for f in findings}
        cases.append(("fetch_sim_same_id", "fetch_sim_same_id" in tags, f"tags={tags}"))

        # 9d) article_body_empty — fetch_sample 의 body_chars 모두 0 (비공개·등급제한 의심)
        body_empty_sample = [{"post_id": "1", "title": "a", "url": "u1", "body_chars": 0},
                             {"post_id": "2", "title": "b", "url": "u2", "body_chars": 0},
                             {"post_id": "3", "title": "c", "url": "u3", "body_chars": 0}]
        conn = _setup_conn()
        findings = inspector.diagnose(
            conn, paths, slug=slug8, subscriptions=[], latest_job=None,
            config={"kwargs": {}}, state=None, fetch_sample=body_empty_sample)
        tags = {f.tag for f in findings}
        cases.append(("article_body_empty", "article_body_empty" in tags, f"tags={tags}"))

        # 9e) body_chars 하나라도 > 0 이면 article_body_empty 안 뜸
        body_some_sample = [{"post_id": "1", "title": "a", "url": "u1", "body_chars": 0},
                            {"post_id": "2", "title": "b", "url": "u2", "body_chars": 1234},
                            {"post_id": "3", "title": "c", "url": "u3", "body_chars": 0}]
        conn = _setup_conn()
        findings = inspector.diagnose(
            conn, paths, slug=slug8, subscriptions=[], latest_job=None,
            config={"kwargs": {}}, state=None, fetch_sample=body_some_sample)
        tags = {f.tag for f in findings}
        cases.append(("article_body_empty_suppressed_when_any_present",
                      "article_body_empty" not in tags, f"tags={tags}"))

        # 9f) body_chars 모두 None (fetch 예외) 이면 article_body_empty 안 뜸 (판정 불가)
        body_none_sample = [{"post_id": "1", "title": "a", "url": "u1", "body_chars": None},
                            {"post_id": "2", "title": "b", "url": "u2", "body_chars": None}]
        conn = _setup_conn()
        findings = inspector.diagnose(
            conn, paths, slug=slug8, subscriptions=[], latest_job=None,
            config={"kwargs": {}}, state=None, fetch_sample=body_none_sample)
        tags = {f.tag for f in findings}
        cases.append(("article_body_empty_skip_when_all_unknown",
                      "article_body_empty" not in tags, f"tags={tags}"))

        # 9b) _latest_register_job_for — json_extract 매칭. user_id 가 username 안에 substring 으로
        # 들어있어도 (예: username = "user_000000000000000000") 다른 사용자의 잡으로 잘못 잡지 않는다.
        slug_x = "j.example.com_x"
        conn = _setup_conn()
        conn.execute(
            "INSERT INTO jobs(kind,url,slug,requested_by,status,created_at) "
            "VALUES('register','u','" + slug_x + "',?,'done',?)",
            (json.dumps({"id": "AAAA", "name": "name-BBBB-suffix"}), _iso(now)))
        # 본인이 BBBB 인 다른 잡
        conn.execute(
            "INSERT INTO jobs(kind,url,slug,requested_by,status,created_at) "
            "VALUES('register','u','" + slug_x + "',?,'done',?)",
            (json.dumps({"id": "BBBB", "name": "name-CCCC-suffix"}), _iso(now)))
        conn.commit()
        latest_bbbb = inspector._latest_register_job_for(conn, user_id="BBBB", slug=slug_x)
        # BBBB 잡만 잡혀야 함 (AAAA 의 username 에 BBBB 가 substring 으로 있어도)
        cases.append(("latest_register_job_strict_match",
                      latest_bbbb is not None
                      and latest_bbbb.get("requested_by", {}).get("id") == "BBBB",
                      f"got {latest_bbbb}"))

        # 9c) format_reports — issue 안의 markdown/줄바꿈 깨지지 않게
        rows_for_fmt = [{"id": 1, "slug": "x", "status": "open", "user_id": "u",
                         "username": "alice", "created_at": "2026-05-14T01:23:45",
                         "issue": "줄바꿈\n그리고 ``코드`` 와 **굵게**"}]
        text = inspector.format_reports(rows_for_fmt)
        cases.append(("format_reports_escapes_markdown",
                      "\n그리고" not in text and "**" in text  # ** 문자는 들어가지만 코드 안이라 무력화
                      and text.count("\n") <= 2  # **신고:** 헤더 + 한 항목 = 2 줄
                      and "ʼ" in text,  # backtick 치환됨
                      f"text={text!r}"))

        # 10) 정상 케이스 — 깨짐 신호 없음
        good_state = {"ok": {"slug": "good", "consecutive_breakage": 0,
                              "last_poll_at": _iso(now - timedelta(hours=2)),
                              "n_baseline": 30}, "failed": None}
        good_sub = {"user_id": "u1", "slug": "good", "url": "https://good.example.com/x",
                    "target_id": "u1", "target_kind": "dm",
                    "created_at": _iso(now - timedelta(days=1)),
                    "filter_prompt": None, "notify_empty": 0}
        conn = _setup_conn()
        findings = inspector.diagnose(
            conn, paths, slug="good", subscriptions=[good_sub], latest_job=None,
            config={"kwargs": {"channel": "x"}}, state=good_state,
            fetch_sample=[{"post_id": "1", "title": "a", "url": "u1"},
                          {"post_id": "2", "title": "b", "url": "u2"}])
        cases.append(("clean_case_no_findings", findings == [], f"findings={[f.tag for f in findings]}"))

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
