"""`generate.validate._STABLE_ID_RE` cap (200자) 가 URL-slug-as-id 패턴을 수용하면서도
공백 / 200자 초과 / 빈 문자열을 여전히 차단하는지 검증.

배경: 64자 cap 은 CNN/NYT/WaPo 류의 date+title-slug URL path (~130자) 를 정상 post_id 임에도
차단했다 (`host_edition-cnn-com_world_ae74b4db` FAILED). cap 200 으로 완화하되 shape 규칙은
유지 — 공백 배제 + 합리적 길이 한도.
"""
from __future__ import annotations

from generate.validate import _STABLE_ID_RE


# (name, value, expect_match)
_FIXTURES: list[tuple[str, str, bool]] = [
    # accept — 짧은 안정 ID
    ("short_numeric", "12345", True),
    ("short_slug", "abc-def", True),
    ("hash_like", "a1b2c3d4e5", True),
    # accept — URL-slug-as-id (관측 사례)
    (
        "cnn_world_video_130char",
        "2026/05/18/world/video/north-korean-womens-soccer-team-arrives-in-south-korea-for-the-first-time-in-over-7-years-ripley-hnk-digvid",
        True,
    ),
    (
        "cnn_china_60char",
        "2026/05/18/china/xi-trump-trade-agreements-china-visit-intl-hnk",
        True,
    ),
    (
        "exactly_200char",
        "a" * 200,
        True,
    ),
    # reject — 공백 (title 실수)
    ("title_with_spaces", "Title with spaces", False),
    ("title_short_with_space", "ab cd", False),
    # reject — 200자 초과
    ("201char", "a" * 201, False),
    # reject — 빈 문자열
    ("empty", "", False),
    # reject — 제어/특수문자
    ("with_question_mark", "abc?def", False),
    ("with_ampersand", "abc&def", False),
]


def run() -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []
    for name, value, expect in _FIXTURES:
        actual = bool(_STABLE_ID_RE.match(value))
        ok = actual == expect
        cases.append((
            f"stable_id_shape__{name}",
            ok,
            f"value={value[:60]!r} (len={len(value)}) expect_match={expect} actual={actual}",
        ))
    return cases


if __name__ == "__main__":
    fail = 0
    for name, ok, msg in run():
        mark = "PASS" if ok else "FAIL"
        print(f"  {mark}  {name}  ({msg})")
        if not ok:
            fail += 1
    raise SystemExit(0 if fail == 0 else 1)
