"""probe.extract._article_url_score — 글 페이지스러운 URL 점수."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import _article_url_score

    cases: list[tuple[str, bool, str]] = []

    host = "x.com"

    # 1. 같은 호스트 + 글ID 숫자 + view 키워드 = 만점
    s1 = _article_url_score("https://x.com/board/view/12345", host)
    cases.append(("same_host_view_id", s1 >= 7, f"got score {s1}"))

    # 2. 다른 호스트는 -1 또는 같은 호스트 가산 X
    s2 = _article_url_score("https://other.com/board/view/12345", host)
    cases.append(("diff_host_lower", s2 < s1, f"got {s2} vs {s1}"))

    # 3. None / 빈값 = -1
    cases.append(("none_returns_neg1", _article_url_score(None, host) == -1, ""))
    cases.append(("empty_returns_neg1", _article_url_score("", host) == -1, ""))

    # 4. 같은 호스트 + 짧은 ID(2자리) → article_hint 만 +1, 숫자 보너스 X
    s4 = _article_url_score("https://x.com/menu/12", host)
    cases.append(("short_id_no_bonus", s4 < s1, f"got {s4}"))

    # 5. 정렬 헤더(myinfo, login) 같은 path = same_host 만
    s5 = _article_url_score("https://x.com/login", host)
    s6 = _article_url_score("https://x.com/board/notice/12345", host)
    cases.append(("login_lower_than_article", s5 < s6, f"login={s5}, article={s6}"))

    # 6. query-heavy 페널티 (2026-05-17): /search?sort=...&filter=... 가 깨끗한 bundle URL 보다 낮아야.
    # humblebundle case: /store/search?sort=bestselling&filter=onsale 가 /software/realm-giants-software 보다 낮아야 함.
    s_search = _article_url_score("https://www.humblebundle.com/store/search?sort=bestselling&filter=onsale", "www.humblebundle.com")
    s_bundle = _article_url_score("https://www.humblebundle.com/software/realm-giants-software", "www.humblebundle.com")
    cases.append((
        "search_filter_penalty_lower_than_clean_path",
        s_search < s_bundle,
        f"search={s_search} bundle={s_bundle}",
    ))

    # 7. /search 경로 페널티 — query 없어도 path 자체가 검색.
    s_search_path = _article_url_score("https://x.com/search/keyword", host)
    s_detail_path = _article_url_score("https://x.com/articles/some-post", host)
    cases.append((
        "search_path_lower_than_detail",
        s_search_path < s_detail_path,
        f"search_path={s_search_path} detail={s_detail_path}",
    ))

    # 8. clean machine-name path 보너스 — 숫자 ID 없는 깨끗한 path 도 글로 인정.
    s_machine = _article_url_score("https://x.com/posts/my-article-slug", host)
    s_root = _article_url_score("https://x.com/login", host)
    cases.append((
        "machine_name_bonus_over_login",
        s_machine > s_root,
        f"machine={s_machine} login={s_root}",
    ))

    # 9. 회귀: 기존 글 URL 들 점수 안 떨어졌나.
    s_view_id = _article_url_score("https://x.com/board/view/12345", host)
    cases.append((
        "regression_view_id_still_high",
        s_view_id >= 7,
        f"view_id={s_view_id}",
    ))

    return cases
