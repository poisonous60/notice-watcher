"""engine.recognizers.dcinside_main — 디시인사이드 정식갤 (모바일 보드) 인식.

`m.dcinside.com/board/<id>` (정식갤) → httpx_html config. 미니/마이너갤
(`gall.dcinside.com/mgallery/...`) 은 dcinside_mgallery 가 담당 — 충돌 X 검증.
2026-05-20-b batch: LLM 이 mobile board → desktop `/board/lists/?id=` 로 rewrite → 404.
인식기로 proven config 고정.
"""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from engine.recognizers import recognize
    from engine.config_schema import validate_config

    cases: list[tuple[str, bool, str]] = []

    # 1~4. 정식갤 모바일 보드 — 인식 + board id 추출 + schema 통과
    for board in ("stock", "nikke", "programming", "baseball_new11"):
        url = f"https://m.dcinside.com/board/{board}"
        r = recognize(url)
        ok = (r is not None and r.get("board") == board
              and r.get("strategy") == "httpx_html"
              and r.get("site") == "m.dcinside.com")
        detail = r.get("board") if (ok and isinstance(r, dict)) else r
        if ok:
            try:
                validate_config(r)
            except Exception as e:  # noqa: BLE001
                ok = False
                detail = f"schema fail: {e}"
        cases.append((f"dcinside_main_{board}", ok, f"got {detail!r}"))

    # 5. desktop 정식갤 list — id 쿼리에서 추출
    r = recognize("https://gall.dcinside.com/board/lists/?id=stock")
    cases.append(("dcinside_main_desktop",
                  r is not None and r.get("board") == "stock" and r.get("strategy") == "httpx_html",
                  f"got {None if r is None else r.get('board')}"))

    # 5b. desktop 정식갤 개념글/검색 탭 — 필터를 list URL + slug 에 보존
    r = recognize("https://gall.dcinside.com/board/lists/?id=stock&exception_mode=recommend&utm_source=x")
    cases.append(("dcinside_main_desktop_filter_preserved",
                  r is not None
                  and r.get("_slug_board") == "stock_exception_mode_recommend"
                  and "exception_mode=recommend" in r.get("list", {}).get("url_template", "")
                  and "utm_source" not in r.get("list", {}).get("url_template", ""),
                  f"got slug={None if r is None else r.get('_slug_board')} list={None if r is None else r.get('list', {}).get('url_template')}"))

    # 6. 미니갤 — dcinside_mgallery 로 가야 함 (dcinside_main 가로채면 X)
    r = recognize("https://gall.dcinside.com/mgallery/board/lists/?id=chokaguyahime")
    cases.append(("mgallery_not_hijacked",
                  r is not None and r.get("adapter") == "DCInsideMGalleryAdapter",
                  f"got {None if r is None else (r.get('adapter') or r.get('strategy'))}"))

    # 6b. 미니갤 전체글 — 필터 없음 → list_params 없고 slug 무접미사
    r = recognize("https://gall.dcinside.com/mgallery/board/lists/?id=thesingularity")
    ok = (r is not None and "list_params" not in (r.get("kwargs") or {})
          and r.get("_slug_board") == "thesingularity")
    cases.append(("mgallery_full_no_filter", ok,
                  f"got kwargs={None if r is None else r.get('kwargs')} slug={None if r is None else r.get('_slug_board')}"))

    # 6c. 미니갤 개념글(recommend) 탭 — exception_mode 보존 → adapter list_params + slug 분리
    r = recognize("https://gall.dcinside.com/mgallery/board/lists/?id=thesingularity&exception_mode=recommend")
    ok = (r is not None
          and (r.get("kwargs") or {}).get("list_params") == {"exception_mode": "recommend"}
          and r.get("_slug_board") == "thesingularity_exception_mode_recommend")
    cases.append(("mgallery_recommend_preserved", ok,
                  f"got kwargs={None if r is None else r.get('kwargs')} slug={None if r is None else r.get('_slug_board')}"))

    # 6d. 미니갤 검색(s_type+s_keyword) — 모든 list 필터 보존 + 한글 키워드 url-encode slug
    r = recognize("https://gall.dcinside.com/mgallery/board/lists/?id=thesingularity&s_type=search_subject_memo&s_keyword=%EC%B9%B4%EC%AB%80%EC%BF%A0")
    lp = (r.get("kwargs") or {}).get("list_params") if r else None
    ok = (r is not None
          and lp == {"s_type": "search_subject_memo", "s_keyword": "카쫀쿠"}
          and r.get("_slug_board") == "thesingularity_s_keyword_%EC%B9%B4%EC%AB%80%EC%BF%A0_s_type_search_subject_memo")
    cases.append(("mgallery_search_preserved", ok,
                  f"got list_params={lp} slug={None if r is None else r.get('_slug_board')}"))

    # 7. action path `/board/lists` (board 이름 아님) — 미인식
    r = recognize("https://m.dcinside.com/board/lists?id=stock")
    cases.append(("mobile_lists_action_passes", r is None or r.get("site") != "m.dcinside.com",
                  f"got {None if r is None else r.get('site')}"))

    # 8. action path `/board/view` — 미인식 (단일 글)
    r = recognize("https://m.dcinside.com/board/view/?id=stock&no=123")
    cases.append(("mobile_view_action_passes", r is None or r.get("site") != "m.dcinside.com",
                  f"got {None if r is None else r.get('site')}"))

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
