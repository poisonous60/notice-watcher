"""bot.site_ops.find_registered_alias — canonical-url 역조회로 slug 스키마 drift 중복 흡수.

recognizer 추가 등으로 같은 board URL 이 다른 slug 를 받을 때, 이미 등록된 기존 slug 를
canonical_url 신원으로 찾아내 2번째 config 중복 등록을 막는지 검증.
임시 STATE_DIR 로 격리(다른 bot 테스트와 동일하게 run() 컨벤션).
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


def _state(d: Path, slug: str, url: str, *, marker: str | None = None) -> None:
    (d / f"{slug}.json").write_text(
        json.dumps({"slug": slug, "url": url, "config_path": f"configs/{slug}.json"}),
        encoding="utf-8",
    )
    if marker:
        (d / f"{slug}.{marker}.json").write_text(json.dumps({"slug": slug}), encoding="utf-8")


def run() -> list[tuple[str, bool, str]]:
    from bot import site_ops

    cases: list[tuple[str, bool, str]] = []
    tmp = Path(tempfile.mkdtemp())
    orig = site_ops.STATE_DIR
    site_ops.STATE_DIR = tmp
    try:
        # 기존 등록: 옛 fallback slug 로 inven maple board 폴링 중
        _state(tmp, "host_inven-co-kr_board_57c4acb4",
               "https://www.inven.co.kr/board/maple/2304")
        # 다른 board (관계 없음)
        _state(tmp, "inven_lol_4625_dc28c50d",
               "https://www.inven.co.kr/board/lol/4625")
        # 차단 마커 달린 board — alias 후보에서 제외돼야
        _state(tmp, "blocked_x", "https://www.inven.co.kr/board/wow/9999", marker="REJECTED")

        # 1) recognizer 가 같은 URL 에 새로 줄 slug 로 조회 → 기존 fallback slug 흡수
        new_slug = "inven_maple_2304_57c4acb4"
        got = site_ops.find_registered_alias(
            "https://www.inven.co.kr/board/maple/2304", exclude_slug=new_slug)
        cases.append(("alias_found", got == "host_inven-co-kr_board_57c4acb4", f"got {got!r}"))

        # 2) canonical 정규화 — 대문자 host / trailing slash 도 같은 board
        #    (?p= 페이징은 canonical 이 보존 → 다른 신원. url_to_slug 와 동일 — dedup 대상 아님)
        got = site_ops.find_registered_alias(
            "https://WWW.inven.co.kr/board/maple/2304/", exclude_slug=new_slug)
        cases.append(("alias_canonical_norm", got == "host_inven-co-kr_board_57c4acb4", f"got {got!r}"))

        # 3) exclude_slug 가 바로 그 등록 slug 면 자기 자신은 후보 제외 → None
        got = site_ops.find_registered_alias(
            "https://www.inven.co.kr/board/maple/2304",
            exclude_slug="host_inven-co-kr_board_57c4acb4")
        cases.append(("alias_excludes_self", got is None, f"got {got!r}"))

        # 4) 등록된 적 없는 board → None (오탐 없음)
        got = site_ops.find_registered_alias(
            "https://www.inven.co.kr/board/ff14/4467", exclude_slug="inven_ff14_4467_x")
        cases.append(("no_match_other_board", got is None, f"got {got!r}"))

        # 5) 차단 마커 board 는 is_registered=False → alias 로 안 잡힘
        got = site_ops.find_registered_alias(
            "https://www.inven.co.kr/board/wow/9999", exclude_slug="inven_wow_9999_x")
        cases.append(("blocked_not_alias", got is None, f"got {got!r}"))

        # 6) 마커 전용 파일(base state 없음) + 깨진 JSON → 크래시 없이 무시
        (tmp / "orphan_marker.FAILED.json").write_text('{"slug":"orphan_marker"}', encoding="utf-8")
        (tmp / "broken.json").write_text("{not valid json", encoding="utf-8")
        try:
            got = site_ops.find_registered_alias(
                "https://www.inven.co.kr/board/maple/2304", exclude_slug="x_new")
            crashed = False
        except Exception:  # noqa: BLE001
            got, crashed = None, True
        cases.append(("marker_only_and_malformed_ignored",
                      not crashed and got == "host_inven-co-kr_board_57c4acb4",
                      f"crashed={crashed} got={got!r}"))
    finally:
        site_ops.STATE_DIR = orig

    # 7) unwatch 양쪽 제거 (codex #1) — old+new slug 양쪽 구독을 URL 해제가 둘 다 지우는지.
    #    핸들러가 쓰는 building block(find_registered_alias + remove_subscription) 조합을 검증.
    import sqlite3 as _sql  # noqa: F401
    from bot import db
    tmp2 = Path(tempfile.mkdtemp())
    conn = db.connect(tmp2 / "t.sqlite3")
    orig2 = site_ops.STATE_DIR
    site_ops.STATE_DIR = tmp2
    try:
        _state(tmp2, "host_inven-co-kr_board_57c4acb4",
               "https://www.inven.co.kr/board/maple/2304")
        url = "https://www.inven.co.kr/board/maple/2304"
        new_slug = "inven_maple_2304_57c4acb4"
        for s in (new_slug, "host_inven-co-kr_board_57c4acb4"):
            db.add_subscription(conn, user_id="u1", slug=s, url=url, filter_prompt=None,
                                schedule="realtime", target_kind="dm", target_id="u1")
        # 핸들러 로직 재현: computed slug 제거 + alias 제거, 합산
        removed = db.remove_subscription(conn, user_id="u1", slug=new_slug)
        alias = site_ops.find_registered_alias(url, exclude_slug=new_slug)
        if alias:
            removed += db.remove_subscription(conn, user_id="u1", slug=alias)
        left = len(db.list_subscriptions(conn, user_id="u1"))
        cases.append(("unwatch_removes_both", removed == 2 and left == 0,
                      f"removed={removed} left={left} alias={alias!r}"))
    finally:
        site_ops.STATE_DIR = orig2
        conn.close()

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
