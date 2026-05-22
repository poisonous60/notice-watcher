"""`generate.validate` 의 nav/연도-아카이브 false-accept 차단 (ADR 0011 fix A).

글-board 인데 row_selector 가 nav/메뉴 chrome 을 가리키거나(openbsd `nav>ul>li`·garuda
`p-menubar-item`) 항목이 연도 인덱스(netbsd 2025/2024/2023)면 폴링해도 nav junk/연도링크만
잡는 false-accept 를 hard fail 로 차단하는지. conjunction(날짜0+숫자0)으로 clojure·version-board
false-reject 방지하는지도 검증.
"""
from __future__ import annotations

from generate.validate import _is_nav_junk_rows, _is_year_archive


def _nav_cases() -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []

    # (label, row_selector, post_ids, any_dated, expect_nav_junk)
    fixtures = [
        # 진짜 nav junk — 거부돼야
        ("openbsd_nav_ul_li", "nav > ul > li", ["goals", "plat", "security", "events"], False, True),
        ("garuda_p_menubar", "#pn_id_9 > li.p-menubar-item", ["home", "editions", "installation"], False, True),
        ("role_navigation", "div[role=navigation] a", ["about", "contact"], False, True),
        # false-reject 방지 — 통과해야
        ("clojure_nav_but_dated_ids", "nav.w-nav-menu.clj-section-nav-menu a",
         ["2026/05/19/deref", "2026/05/12/clojure"], False, False),  # id 에 숫자 → 면제
        ("clojure_nav_but_published", "nav.w-nav-menu a", ["deref", "clojure"], True, False),  # 날짜 있음 → 면제
        ("bun_blogcard_no_nav_token", "section > div > a.BlogCard", ["bun-v1", "bun"], False, False),  # nav-token 없음
        ("real_board_table", "tbody > tr", ["welcome", "rules"], False, False),  # nav-token 없음 (짧은 제목이어도 OK)
        ("empty_ids", "nav > ul > li", [], False, False),  # 항목 0 → 판정 보류
        ("navbar_but_digit_id", "ul.navbar-nav > li", ["v2", "v3"], False, False),  # 숫자 id → 면제
    ]
    for label, sel, ids, dated, expect in fixtures:
        got = _is_nav_junk_rows(sel, ids, dated)
        cases.append((f"nav_junk:{label}", got == expect, f"got={got} expect={expect} sel={sel!r} ids={ids}"))

    # 연도 아카이브
    year_fixtures = [
        ("netbsd_years", ["2025", "2024", "2023"], True),
        ("voidlinux_single_year", ["2026"], True),
        ("version_dotted_not_year", ["9.5.1", "8.14.5"], False),
        ("php_underscore_not_year", ["8_5_5", "8_2_30"], False),
        ("dated_slug_not_year", ["2026/05/19/deref"], False),
        ("mixed_year_and_post", ["2025", "kali-linux-2026"], False),
        ("empty", [], False),
    ]
    for label, ids, expect in year_fixtures:
        got = _is_year_archive(ids)
        cases.append((f"year_archive:{label}", got == expect, f"got={got} expect={expect} ids={ids}"))

    return cases


def run() -> list[tuple[str, bool, str]]:
    return _nav_cases()


if __name__ == "__main__":
    fail = 0
    for name, ok, msg in run():
        mark = "PASS" if ok else "FAIL"
        print(f"  {mark}  {name}  ({msg})")
        if not ok:
            fail += 1
    raise SystemExit(0 if fail == 0 else 1)
