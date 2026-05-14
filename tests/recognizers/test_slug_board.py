"""각 recognizer 가 `_slug_board` 키를 cfg 에 올바르게 채워넣는지 + fallback 동작 확인.

`engine.slug.url_to_slug` 가 `<platform>_<board-id>_<hash>` 형식을 만들 때 이 키를 사용. 누락되면
fallback 으로 cfg['board'] 의 `/` `:` 만 치환해 사용 — 그건 덜 친화적이라 각 recognizer 는 *반드시*
`_slug_board` 를 채워야 함.
"""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from engine.recognizers import recognize
    from engine.slug import platform_and_board

    cases: list[tuple[str, bool, str]] = []

    # 7 recognizers — 각각 platform + board 가 의도된 값인지
    samples = [
        ("arca-live", "trickcal",
         "https://arca.live/b/trickcal"),
        ("arca-live", "trickcal_%EA%B3%B5%EC%8B%9D",
         "https://arca.live/b/trickcal?category=공식"),
        ("naver-cafe", "30291108_6",
         "https://cafe.naver.com/f-e/cafes/30291108/menus/6"),
        ("daum-cafe", "umamusume-kor_Z4os",
         "https://m.cafe.daum.net/umamusume-kor/Z4os"),
        ("dcinside-mgallery", "chokaguyahime",
         "https://gall.dcinside.com/mgallery/board/lists/?id=chokaguyahime"),
        ("nexon-forum", "bluearchive_1018",
         "https://forum.nexon.com/bluearchive/board_list?board=1018"),
        ("naver-game-lounge", "Trickcal_3",
         "https://game.naver.com/lounge/Trickcal/board/3"),
        ("reddit", "CosmicPrincessKaguya",
         "https://www.reddit.com/r/CosmicPrincessKaguya/"),
    ]
    for expected_plat, expected_board, url in samples:
        cfg = recognize(url)
        ok = cfg is not None and cfg.get("_recognized_platform") == expected_plat and \
             cfg.get("_slug_board") == expected_board
        cases.append((
            f"slug_board_{expected_plat}_{expected_board[:20]}",
            ok,
            f"got platform={cfg and cfg.get('_recognized_platform')!r} "
            f"_slug_board={cfg and cfg.get('_slug_board')!r}",
        ))

    # fallback — 미등록 URL 의 host 기반 platform_and_board
    plat, board = platform_and_board("https://cse.skku.edu/cse/notice.do?mode=list")
    cases.append((
        "fallback_skku",
        plat == "host_cse-skku-edu" and board == "cse",
        f"got platform={plat!r} board={board!r}",
    ))

    plat, board = platform_and_board("https://www.gamemeca.com/news.php?ca=P")
    cases.append((
        "fallback_gamemeca_www_stripped",
        plat == "host_gamemeca-com" and board == "news.php",
        f"got platform={plat!r} board={board!r}",
    ))

    plat, board = platform_and_board("https://example.com/")
    cases.append((
        "fallback_root_path",
        plat == "host_example-com" and board == "root",
        f"got platform={plat!r} board={board!r}",
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
