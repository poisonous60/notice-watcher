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

    # 12. USHMM Encyclopedia — skip_learn=True (보드 인덱스 `/content/<lang>` 가 같은 `/content` 공유)
    out = recognize_reject("https://encyclopedia.ushmm.org/content/en/article/the-great-depression")
    cases.append(("ushmm_article",
                  out is not None and "USHMM" in out[1] and out[2] is True,
                  f"got {out!r}"))

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

    # 19. nature.com 단일 article — skip_learn=True (보드 `/articles?type=news` 가 같은 first segment)
    out = recognize_reject("https://www.nature.com/articles/d41586-018-05791-w")
    cases.append(("nature_article",
                  out is not None and out[0] == "article_page_reject" and "nature.com" in out[1] and out[2] is True,
                  f"got {out!r}"))

    # 20. nature.com 보드 (쿼리 있는 list) — 통과
    out = recognize_reject("https://www.nature.com/articles?type=news")
    cases.append(("nature_board_with_query_passes", out is None, f"got {out!r}"))

    # 21. nature.com 다른 섹션 보드 — 통과
    out = recognize_reject("https://www.nature.com/news")
    cases.append(("nature_news_section_passes", out is None, f"got {out!r}"))

    # 22. iln.ieee.org ContentDetails — skip_learn=True (보드 `/Public/trainingcatalog.aspx` 가 같은 `/Public`)
    out = recognize_reject("https://iln.ieee.org/Public/ContentDetails.aspx?id=9D3FE9C6144F4C298ABDE18D84EDB93C")
    cases.append(("iln_ieee_content_details",
                  out is not None and "iln.ieee.org" in out[1] and out[2] is True,
                  f"got {out!r}"))

    # 23. iln.ieee.org 보드 (trainingcatalog) — 통과
    out = recognize_reject("https://iln.ieee.org/Public/trainingcatalog.aspx")
    cases.append(("iln_ieee_catalog_passes", out is None, f"got {out!r}"))

    # 24. jobplanet news-<N> 기사 — skip_learn=True (보드 `/contents/news` 가 같은 `/contents`)
    out = recognize_reject("https://www.jobplanet.co.kr/contents/news-616")
    cases.append(("jobplanet_news_article",
                  out is not None and "jobplanet" in out[1] and out[2] is True,
                  f"got {out!r}"))

    # 25. jobplanet 보드 `/contents/news` (트레일링 -N 없음) — 통과
    out = recognize_reject("https://www.jobplanet.co.kr/contents/news")
    cases.append(("jobplanet_board_passes", out is None, f"got {out!r}"))

    # 26. 위키 패턴은 skip_learn=True — 보드 (/wiki/Special:RecentChanges 등) 가 같은 첫 path segment 공유
    out = recognize_reject("https://en.wikipedia.org/wiki/Nazi_Party")
    cases.append(("wikipedia_skip_learn_true",
                  out is not None and out[2] is True,
                  f"got {out!r}"))

    # 26b. Wikipedia Special:RecentChanges with query — 통과 (board, not article)
    out = recognize_reject("https://en.wikipedia.org/wiki/Special:RecentChanges?hidebots=1&limit=50&days=1&urlversion=2")
    cases.append(("wikipedia_recent_changes_passes", out is None, f"got {out!r}"))

    # 27. MDN docs ko (host_developer-mozil_ko_47b50435) — skip_learn=True (host_path_prefix=lang)
    out = recognize_reject("https://developer.mozilla.org/ko/docs/Web/HTML/Reference/Elements/button")
    cases.append(("mdn_docs_ko",
                  out is not None and "MDN" in out[1] and out[2] is True,
                  f"got {out!r}"))

    # 28. MDN docs en-US
    out = recognize_reject("https://developer.mozilla.org/en-US/docs/Web/HTML/Element/button")
    cases.append(("mdn_docs_en",
                  out is not None and "MDN" in out[1],
                  f"got {out!r}"))

    # 29. MDN Blog — 통과 (보드 가능)
    out = recognize_reject("https://developer.mozilla.org/en-US/blog/")
    cases.append(("mdn_blog_passes", out is None, f"got {out!r}"))

    # 30. github-wiki-see.page wiki 미러 (host_github-wiki-see_m_6c370ddf)
    out = recognize_reject("https://github-wiki-see.page/m/goofcode/UR/wiki/%EB%85%BC%EB%AC%B8-%EC%9D%BD%EB%8A%94-%EB%B2%95")
    cases.append(("github_wiki_see",
                  out is not None and "wiki" in out[1] and out[2] is False,
                  f"got {out!r}"))

    # 31. github-wiki-see 루트 — 통과 (목록 페이지 가능성)
    out = recognize_reject("https://github-wiki-see.page/")
    cases.append(("github_wiki_see_root_passes", out is None, f"got {out!r}"))

    # 32. ktword 용어집 (host_ktword-co-kr_test_d081a15f) — skip_learn=False (host 전체 article-only)
    out = recognize_reject("http://www.ktword.co.kr/test/view/view.php?m_temp1=3801")
    cases.append(("ktword_view",
                  out is not None and "ktword" in out[1] and out[2] is False,
                  f"got {out!r}"))

    # 33. ktword 다른 view path — 통과
    out = recognize_reject("http://www.ktword.co.kr/test/abbr_view/list_letter.php")
    cases.append(("ktword_other_path_passes", out is None, f"got {out!r}"))

    # 34. OpenAI /index/<slug>/ (host_openai-com_index_47fc1c1b)
    out = recognize_reject("https://openai.com/index/attacking-machine-learning-with-adversarial-examples/")
    cases.append(("openai_index_article",
                  out is not None and "openai" in out[1] and out[2] is False,
                  f"got {out!r}"))

    # 35. OpenAI /news/ 보드 — 통과 (보드 URL 은 통과시켜야 함; 차단은 별도 이슈)
    out = recognize_reject("https://openai.com/news/")
    cases.append(("openai_news_passes", out is None, f"got {out!r}"))

    # 36. OpenAI /index/ root (no slug) — 통과
    out = recognize_reject("https://openai.com/index/")
    cases.append(("openai_index_root_passes", out is None, f"got {out!r}"))

    # 37. Tistory 메인 (host_tistory-com_root_c59077fa) — skip_learn=True (host 전체 hub)
    out = recognize_reject("https://www.tistory.com/")
    cases.append(("tistory_root_www",
                  out is not None and "tistory" in out[1] and out[2] is True,
                  f"got {out!r}"))

    # 38. Tistory naked root
    out = recognize_reject("https://tistory.com/")
    cases.append(("tistory_root_naked", out is not None and "tistory" in out[1], f"got {out!r}"))

    # 39. Tistory 개별 블로그 — 통과 (subdomain 별도 host)
    out = recognize_reject("https://ohokja1940.tistory.com/1976")
    cases.append(("tistory_subdomain_passes", out is None, f"got {out!r}"))

    # 40. Tistory 메인 카테고리 query — 거부 (메인 hub 의 변형)
    out = recognize_reject("https://www.tistory.com/?category=travel")
    cases.append(("tistory_root_with_query", out is not None and "tistory" in out[1], f"got {out!r}"))

    # 41. SUMO docs (host_sumo-dlr-de_docs_3634ca61) — mkdocs static docs, skip_learn=False
    out = recognize_reject("https://sumo.dlr.de/docs/Definition_of_Vehicles,_Vehicle_Types,_and_Routes.html")
    cases.append(("sumo_docs_page",
                  out is not None and "sumo" in out[1] and out[2] is False,
                  f"got {out!r}"))

    # 42. SUMO docs root — also blocked (정적 docs hub, 어떤 path 든 폴링 대상 X)
    out = recognize_reject("https://sumo.dlr.de/docs/index.html")
    cases.append(("sumo_docs_index", out is not None and "sumo" in out[1], f"got {out!r}"))

    # 43. SUMO 다른 path — 통과 (skip_learn=False 이지만 path_prefix=`/docs` 만 차단)
    out = recognize_reject("https://sumo.dlr.de/")
    cases.append(("sumo_root_passes", out is None, f"got {out!r}"))

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
