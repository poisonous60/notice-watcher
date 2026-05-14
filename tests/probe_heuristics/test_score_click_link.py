"""probe.fetch_headless._score_click_link — 클릭 후보 점수화."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from probe.fetch_headless import _score_click_link

    cases: list[tuple[str, bool, str]] = []

    host = "x.com"

    # 1. 진짜 글 링크 — 같은 호스트 + 글ID + 적정 텍스트 길이 = 고득점
    article = {"href": "/board/view/12345", "text": "공지: 5월 점검 안내", "dataAttrs": {},
               "visible": True}
    s_article = _score_click_link(article, page_host=host)
    cases.append(("article_high_score", s_article >= 5, f"got {s_article}"))

    # 2. 로그인 nav junk = -100
    login = {"href": "/login", "text": "로그인", "dataAttrs": {}, "visible": True}
    s_login = _score_click_link(login, page_host=host)
    cases.append(("login_junk_neg100", s_login <= -100, f"got {s_login}"))

    # 3. 글쓰기·이전·다음 junk
    write = {"href": "/write", "text": "글쓰기", "dataAttrs": {}, "visible": True}
    cases.append(("write_junk_neg",
                  _score_click_link(write, page_host=host) <= -100, ""))
    prev = {"href": "?page=1", "text": "이전", "dataAttrs": {}, "visible": True}
    cases.append(("prev_junk_neg",
                  _score_click_link(prev, page_host=host) <= -100, ""))

    # 4. 다른 호스트 = 같은 호스트보다 낮음
    other = {"href": "https://other.com/view/12345", "text": "글 제목 12345",
             "dataAttrs": {}, "visible": True}
    s_other = _score_click_link(other, page_host=host)
    cases.append(("other_host_lower",
                  s_other < s_article, f"other={s_other}, article={s_article}"))

    # 5. javascript: href + data-id 보너스
    js_link = {"href": "javascript:goView(12345)", "text": "글 제목 12345",
               "dataAttrs": {"data-id": "12345"}, "visible": True}
    s_js = _score_click_link(js_link, page_host=host)
    js_no_data = {"href": "javascript:void(0)", "text": "...",
                  "dataAttrs": {}, "visible": True}
    s_js_no = _score_click_link(js_no_data, page_host=host)
    cases.append(("js_with_data_id_higher",
                  s_js > s_js_no, f"with_data={s_js}, without={s_js_no}"))

    # 6. tab/sort 파라미터 페널티
    tab = {"href": "/board?tab=hot", "text": "인기글", "dataAttrs": {}, "visible": True}
    s_tab = _score_click_link(tab, page_host=host)
    cases.append(("tab_param_penalized", s_tab < s_article, f"tab={s_tab}, article={s_article}"))

    return cases
