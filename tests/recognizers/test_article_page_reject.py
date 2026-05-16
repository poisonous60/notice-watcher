"""engine.recognizers.article_page_reject — 알려진 백과/사전 호스트 단일 article URL fast-path 거부.

이 모듈은 일반 인식기(PATTERNS) 가 아니라 PATTERNS_REJECT 만 export. recognize_reject(url) 가
매칭되면 (NAME, reason) 반환. register.py 가 probe 전에 호출해 즉시 REJECTED + learned_blacklist.

false positive 0 필수 — 사용자가 *목록 페이지* 로 줄 수 있는 URL (분류/카테고리/Special) 통과 검증.
"""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from engine.recognizers import recognize_reject

    cases: list[tuple[str, bool, str]] = []

    # 1. wikipedia 단일 article — 한국어
    out = recognize_reject("https://ko.wikipedia.org/wiki/%EC%99%95%EC%88%98%EC%9D%B8")
    cases.append(("ko_wikipedia_article",
                  out is not None and out[0] == "article_page_reject" and "위키피디아" in out[1],
                  f"got {out!r}"))

    # 2. wikipedia 단일 article — 영어
    out = recognize_reject("https://en.wikipedia.org/wiki/Nazi_Party")
    cases.append(("en_wikipedia_article",
                  out is not None and out[0] == "article_page_reject",
                  f"got {out!r}"))

    # 3. wikipedia Special:RecentChanges — 분류/특수 페이지는 통과 (false positive 차단)
    out = recognize_reject("https://en.wikipedia.org/wiki/Special:RecentChanges")
    cases.append(("wikipedia_special_passes", out is None, f"got {out!r}"))

    # 4. wikipedia 분류: (URL-encoded) — 분류페이지 통과
    out = recognize_reject("https://ko.wikipedia.org/wiki/%EB%B6%84%EB%A5%98:%ED%95%9C%EA%B5%AD%EC%9D%98_%EC%82%AC%EB%9E%8C")
    cases.append(("wikipedia_category_passes_encoded", out is None, f"got {out!r}"))

    # 5. wikipedia 분류: (한글 직접) — 분류페이지 통과
    out = recognize_reject("https://ko.wikipedia.org/wiki/분류:한국의_사람")
    cases.append(("wikipedia_category_passes_raw", out is None, f"got {out!r}"))

    # 6. 네이버 지식백과 entry.naver
    out = recognize_reject("https://terms.naver.com/entry.naver?docId=3579743&cid=59054&categoryId=59061")
    cases.append(("naver_terms_entry",
                  out is not None and "지식백과" in out[1],
                  f"got {out!r}"))

    # 7. 네이버 지식백과 entry.nhn (legacy)
    out = recognize_reject("https://terms.naver.com/entry.nhn?docId=123")
    cases.append(("naver_terms_entry_nhn", out is not None, f"got {out!r}"))

    # 8. 네이버 지식백과 list.naver — 통과 (인덱스 페이지)
    out = recognize_reject("https://terms.naver.com/list.naver")
    cases.append(("naver_terms_list_passes", out is None, f"got {out!r}"))

    # 9. Britannica /event/
    out = recognize_reject("https://www.britannica.com/event/Great-Depression")
    cases.append(("britannica_event",
                  out is not None and "Britannica" in out[1],
                  f"got {out!r}"))

    # 10. Britannica /place/
    out = recognize_reject("https://www.britannica.com/place/Korea")
    cases.append(("britannica_place", out is not None, f"got {out!r}"))

    # 11. Britannica /quizzes — 통과 (단일 article 형식 아님)
    out = recognize_reject("https://www.britannica.com/quizzes")
    cases.append(("britannica_quizzes_passes", out is None, f"got {out!r}"))

    # 12. USHMM Encyclopedia
    out = recognize_reject("https://encyclopedia.ushmm.org/content/en/article/the-great-depression")
    cases.append(("ushmm_article", out is not None, f"got {out!r}"))

    # 13. USHMM 인덱스 — 통과
    out = recognize_reject("https://encyclopedia.ushmm.org/content/en")
    cases.append(("ushmm_index_passes", out is None, f"got {out!r}"))

    # 14. 일반 board URL — 통과 (false positive 차단)
    out = recognize_reject("https://www.omate.kr/news/articleList.html?view_type=sm")
    cases.append(("omate_board_passes", out is None, f"got {out!r}"))

    # 15. arca.live 채널 — 통과
    out = recognize_reject("https://arca.live/b/trickcal")
    cases.append(("arca_board_passes", out is None, f"got {out!r}"))

    # 16. holocaustexplained — 인식기 미커버, 통과 (nav-only heuristic 가 catch)
    out = recognize_reject("https://www.theholocaustexplained.org/the-nazi-rise-to-power/the-nazi-rise-to-power/the-role-of-economic-instability/")
    cases.append(("theholocaustexplained_passes", out is None, f"got {out!r}"))

    # 17. 빈 url
    out = recognize_reject("")
    cases.append(("empty_url_returns_none", out is None, f"got {out!r}"))

    # 18. 위키 호스트 typo — 통과 (recognizer 매칭 X)
    out = recognize_reject("https://en.wikipediaa.org/wiki/Test")
    cases.append(("wikipedia_typo_passes", out is None, f"got {out!r}"))

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
