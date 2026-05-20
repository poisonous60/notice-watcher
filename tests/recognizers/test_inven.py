"""engine.recognizers.inven — 인벤 게시판 httpx_html config.

표준 round-trip(기존 멤버 config 재현) 대신:
  자동생성 6 멤버(ff14/party6510/lostark/maple/lol/party6181)가 동일 DOM 을 제각기 다른 selector·
  title 전략으로 캡처한 LLM noise 였음(라이브 probe 로 단일 CMS 확인, docs/cases/inven-recognizer.md).
  → 어느 멤버도 canonical 로 채택 안 함 → 멤버별 재현 비교 무의미.
대신: URL→(game,board) 추출 + builder 필드 shape + recognize() 통합 + 같은-host 다른-종류 negative.
(selector 정확성은 등록 시점 라이브 probe 로 검증 완료 — 단위테스트는 네트워크 X.)
"""
from __future__ import annotations

from pathlib import Path


def run() -> list[tuple[str, bool, str]]:
    from engine.recognizers.inven import _build, PATTERNS
    from engine.recognizers import recognize

    pat = PATTERNS[0][0]

    def _try(url: str):
        m = pat.search(url)
        return _build(m, url) if m else None

    cases: list[tuple[str, bool, str]] = []

    # 1) 6 멤버 URL → game/board 추출 + 필드 박힘
    members = [
        ("https://www.inven.co.kr/board/ff14/4467", "ff14", "4467"),
        ("https://www.inven.co.kr/board/party/6510", "party", "6510"),
        ("https://www.inven.co.kr/board/lostark/4811", "lostark", "4811"),
        ("https://www.inven.co.kr/board/maple/2304", "maple", "2304"),
        ("https://www.inven.co.kr/board/lol/4625", "lol", "4625"),
        ("https://www.inven.co.kr/board/party/6181", "party", "6181"),
    ]
    for url, game, board in members:
        cfg = _try(url)
        ok = (
            cfg is not None
            and cfg.get("board") == f"{game}/{board}"
            and cfg.get("_slug_board") == f"{game}_{board}"
            and cfg["list"]["url_template"] == f"https://www.inven.co.kr/board/{game}/{board}"
            and cfg["site"] == "www.inven.co.kr"
            and cfg["strategy"] == "httpx_html"
        )
        tag = url.split("/board/")[1]
        cases.append((f"extract[{tag}]", ok,
                      f"board={cfg and cfg.get('board')!r} slug={cfg and cfg.get('_slug_board')!r}"))

    # 2) builder 필드 shape — 핵심 list/article 필드 존재
    cfg = _try("https://www.inven.co.kr/board/lol/4625")
    shape_ok = (
        cfg is not None
        and set(cfg["list"]["fields"]) >= {"post_id", "title", "url", "author", "published_at"}
        and cfg["list"]["pagination"] == {"kind": "query_param", "page_param": "p"}
        and len(cfg["article"]["content"]) >= 2
        and set(cfg["article"]["enrich"]) >= {"title", "published_at", "author"}
    )
    cases.append(("field_shape", shape_ok, f"fields={cfg and list(cfg['list']['fields'])}"))

    # 3) www 없는 host 도 매칭
    cfg = _try("https://inven.co.kr/board/wow/1234")
    cases.append(("no_www_matches", cfg is not None and cfg.get("board") == "wow/1234",
                  f"got {cfg and cfg.get('board')!r}"))

    # 4) ?p= 페이징 쿼리 붙어도 매칭
    cfg = _try("https://www.inven.co.kr/board/lol/4625?p=3")
    cases.append(("query_suffix_matches", cfg is not None and cfg.get("board") == "lol/4625",
                  f"got {cfg and cfg.get('board')!r}"))

    # 5) recognize() 통합 — _recognized_platform=inven
    cfg = recognize("https://www.inven.co.kr/board/maple/2304")
    cases.append(("recognize_integration",
                  cfg is not None and cfg.get("_recognized_platform") == "inven",
                  f"got {cfg and cfg.get('_recognized_platform')!r}"))

    # 6) 다른-host negative
    cfg = recognize("https://www.dcinside.com/board/lol/4625")
    cases.append(("other_host_negative", cfg is None or cfg.get("_recognized_platform") != "inven",
                  f"got {cfg and cfg.get('_recognized_platform')!r}"))

    # 7) 같은-host 다른-종류 negative (false-match 핵심 가드 — SKILL §4):
    #    개별 글(segment 1개 더)·webzine·게시판 그룹(id 없음)은 board 목록이 아님 → inven 으로 잡히면 안 됨.
    same_host_neg = [
        "https://www.inven.co.kr/board/lol/4625/845852",   # 개별 글 (post_id segment)
        "https://www.inven.co.kr/webzine/news/",            # 웹진 (다른 DOM 타입)
        "https://www.inven.co.kr/board/lol",                # 게시판 그룹 (board_id 없음)
        "https://www.inven.co.kr/lol",                      # 게임 포털 (/board/ 아님)
    ]
    for u in same_host_neg:
        r = recognize(u)
        hit = r is not None and r.get("_recognized_platform") == "inven"
        tag = u.split("inven.co.kr")[1][:24]
        cases.append((f"same_host_neg[{tag}]", not hit,
                      f"recognize→ {r and r.get('_recognized_platform')!r} (None/타platform 이어야)"))

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
