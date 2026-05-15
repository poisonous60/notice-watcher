"""engine.slug.url_to_slug — `<platform>_<board-id>_<hash>` 형식 단언.

probe.paths.url_to_slug 는 이 함수의 thin re-export. probe_smoke stage 5 가 이 fixture 를 자동 로드.
"""
from __future__ import annotations

covers = ["url_to_slug"]


def run() -> list[tuple[str, bool, str]]:
    from probe.paths import url_to_slug

    cases: list[tuple[str, bool, str]] = []

    # 1. recognized arca — platform_channel_hash 형식
    out = url_to_slug("https://arca.live/b/trickcal")
    cases.append((
        "recognized_arca",
        out.startswith("arca-live_trickcal_") and len(out.rsplit("_", 1)[-1]) == 8,
        f"got {out!r}",
    ))

    # 2. arca 채널 + category — 같은 채널이라도 hash 가 다름
    a = url_to_slug("https://arca.live/b/trickcal")
    b = url_to_slug("https://arca.live/b/trickcal?category=공식")
    cases.append((
        "arca_category_distinct_hash",
        a != b and b.startswith("arca-live_trickcal_%"),
        f"a={a!r}, b={b!r}",
    ))

    # 3. naver-cafe — cafe_id + menu_id
    out = url_to_slug("https://cafe.naver.com/f-e/cafes/30291108/menus/6?viewType=L")
    cases.append((
        "recognized_naver_cafe",
        out.startswith("naver-cafe_30291108_6_") and len(out.rsplit("_", 1)[-1]) == 8,
        f"got {out!r}",
    ))

    # 4. dcinside — 옛 115자 케이스가 새 schema 에선 짧음
    out = url_to_slug(
        "https://gall.dcinside.com/mgallery/board/lists/?id=chokaguyahime"
        "&sort_type=N&exception_mode=recommend&search_head=100&page=1"
    )
    cases.append((
        "recognized_dcinside_short",
        out.startswith("dcinside-mgallery_chokaguyahime_") and len(out) <= 100,
        f"len={len(out)} got {out!r}",
    ))

    # 5. nexon-forum
    out = url_to_slug("https://forum.nexon.com/bluearchive/board_list?board=1018")
    cases.append((
        "recognized_nexon_forum",
        out.startswith("nexon-forum_bluearchive_1018_"),
        f"got {out!r}",
    ))

    # 6. naver-game-lounge
    out = url_to_slug("https://game.naver.com/lounge/Trickcal/board/3")
    cases.append((
        "recognized_naver_game_lounge",
        out.startswith("naver-game-lounge_Trickcal_3_"),
        f"got {out!r}",
    ))

    # 7. reddit
    out = url_to_slug("https://www.reddit.com/r/CosmicPrincessKaguya/")
    cases.append((
        "recognized_reddit",
        out.startswith("reddit_CosmicPrincessKaguya_"),
        f"got {out!r}",
    ))

    # 8. unrecognized → host fallback
    out = url_to_slug("https://cse.skku.edu/cse/notice.do?mode=list&srCategoryId1=1582")
    cases.append((
        "fallback_host",
        out.startswith("host_cse-skku-edu_cse_"),
        f"got {out!r}",
    ))

    # 9. deterministic — 같은 URL → 같은 slug
    u = "https://endfield.gryphline.com/ko-kr/news"
    cases.append(("deterministic", url_to_slug(u) == url_to_slug(u), ""))

    # 10. canonical normalization — trailing slash, scheme, host case 같음
    a = url_to_slug("https://arca.live/b/trickcal")
    b = url_to_slug("https://arca.live/b/trickcal/")
    c = url_to_slug("http://arca.live/b/trickcal")
    d = url_to_slug("https://Arca.Live/b/trickcal")
    cases.append((
        "canonical_normalization",
        a == b == c == d,
        f"a={a!r}, b={b!r}, c={c!r}, d={d!r}",
    ))

    # 11. query order normalized — `?a=1&b=2` == `?b=2&a=1`
    a = url_to_slug("https://cafe.naver.com/f-e/cafes/30291108/menus/6?viewType=L&foo=1")
    b = url_to_slug("https://cafe.naver.com/f-e/cafes/30291108/menus/6?foo=1&viewType=L")
    cases.append(("query_order_normalized", a == b, f"a={a!r}, b={b!r}"))

    # 12. arca 의 unknown query → fast-path 거부 → host fallback (platform 이 다름)
    a = url_to_slug("https://arca.live/b/trickcal")
    b = url_to_slug("https://arca.live/b/trickcal?unknown=1")
    cases.append((
        "arca_unknown_query_falls_back",
        a != b and b.startswith("host_arca-live_") and a.startswith("arca-live_"),
        f"a={a!r}, b={b!r}",
    ))

    # 13. 모든 slug ≤ 100자
    samples = [
        "https://gall.dcinside.com/mgallery/board/lists/?id=chokaguyahime&sort_type=N&exception_mode=recommend&search_head=100&page=1",
        "https://x.example.com/a/very/long/path/with/many/segments/and?lots=of&query=params&too=many",
        "https://arca.live/b/" + ("x" * 200),
    ]
    cases.append((
        "length_cap_100",
        all(len(url_to_slug(u)) <= 100 for u in samples),
        f"max={max(len(url_to_slug(u)) for u in samples)}",
    ))

    # 14. hash 부분이 항상 8자 hex
    import re as _re
    out = url_to_slug("https://arca.live/b/trickcal")
    last = out.rsplit("_", 1)[-1]
    cases.append((
        "hash_is_8_hex",
        _re.fullmatch(r"[0-9a-f]{8}", last) is not None,
        f"got hash={last!r}",
    ))

    # 15. tracking query (utm_*, fbclid, ...) drop — 같은 채널 변형 URL 이 한 slug 로 합쳐짐
    base = url_to_slug("https://arca.live/b/trickcal?category=%EA%B3%B5%EC%8B%9D")
    with_utm = url_to_slug("https://arca.live/b/trickcal?category=%EA%B3%B5%EC%8B%9D&utm_source=fb")
    with_fbclid = url_to_slug("https://arca.live/b/trickcal?category=%EA%B3%B5%EC%8B%9D&fbclid=abc")
    cases.append((
        "tracking_query_dropped_recognized",
        base == with_utm == with_fbclid,
        f"base={base!r} +utm={with_utm!r} +fbclid={with_fbclid!r}",
    ))

    # 16. 카페 — recognizer 매칭 케이스도 utm 변형이 같은 slug
    a = url_to_slug("https://cafe.naver.com/f-e/cafes/30291108/menus/6?viewType=L")
    b = url_to_slug("https://cafe.naver.com/f-e/cafes/30291108/menus/6?viewType=L&utm_source=fb")
    cases.append((
        "tracking_query_dropped_cafe",
        a == b,
        f"a={a!r} b={b!r}",
    ))

    # 17. 사이트 의미 query (`category=...`) 는 보존 — 다른 게시판은 다른 slug
    p = url_to_slug("https://arca.live/b/trickcal?category=%EA%B3%B5%EC%8B%9D")
    q = url_to_slug("https://arca.live/b/trickcal?category=%EC%9E%A1%EB%8B%B4")
    cases.append((
        "meaningful_query_preserved",
        p != q,
        f"공식={p!r} 잡담={q!r}",
    ))

    return cases
