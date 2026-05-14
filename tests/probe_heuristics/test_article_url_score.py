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

    return cases
