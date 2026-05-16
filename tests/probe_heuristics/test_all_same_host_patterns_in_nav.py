"""probe.extract.all_same_host_patterns_in_nav — same-host repeating pattern 의 DOM ancestor 가
*전부* nav/aside/header/footer 안인가. True 면 single-article 페이지 신호 (사이드바/topic-nav 메뉴만
잡힘 — main content 의 board list 없음).

scripts/register.py `_single_article_nav_only_check` gate 가 이 신호 보고 거부 — `_board_shape_check`
의 `n_html_same` false-positive 차단 (theholocaustexplained 류 unknown host).

false positive 0 필수 — board 페이지의 main list 가 nav 안에 있으면 절대 거부 X.
"""
from __future__ import annotations


_BOARD_MAIN_LIST_HTML = """
<html><body>
  <nav id="topnav"><ul><li><a href="https://board.example.com/notice/">공지</a></li>
    <li><a href="https://board.example.com/free/">자유</a></li>
    <li><a href="https://board.example.com/event/">이벤트</a></li>
    <li><a href="https://board.example.com/tip/">팁</a></li>
    <li><a href="https://board.example.com/qna/">Q&amp;A</a></li></ul></nav>
  <main>
    <ul class="board-list">
      <li class="row"><a href="https://board.example.com/view/101">글 101</a></li>
      <li class="row"><a href="https://board.example.com/view/102">글 102</a></li>
      <li class="row"><a href="https://board.example.com/view/103">글 103</a></li>
      <li class="row"><a href="https://board.example.com/view/104">글 104</a></li>
      <li class="row"><a href="https://board.example.com/view/105">글 105</a></li>
    </ul>
  </main>
</body></html>
"""

_NAV_ONLY_HTML = """
<html><body>
  <nav id="topics-nav">
    <ul class="tertiary-level">
      <li class="tertiary-li"><a href="https://www.theholocaustexplained.org/the-nazi-rise-to-power/the-nazi-rise-to-power/reichstag-fire/">Reichstag Fire</a></li>
      <li class="tertiary-li"><a href="https://www.theholocaustexplained.org/the-nazi-rise-to-power/the-nazi-rise-to-power/sa-and-ss/">SA and SS</a></li>
      <li class="tertiary-li"><a href="https://www.theholocaustexplained.org/the-nazi-rise-to-power/the-nazi-rise-to-power/propaganda/">Propaganda</a></li>
      <li class="tertiary-li"><a href="https://www.theholocaustexplained.org/the-nazi-rise-to-power/the-nazi-rise-to-power/economic-instability/">Economic Instability</a></li>
      <li class="tertiary-li"><a href="https://www.theholocaustexplained.org/the-nazi-rise-to-power/the-nazi-rise-to-power/political-instability/">Political Instability</a></li>
    </ul>
  </nav>
  <article>본문 텍스트 — anchor 없음 — 단일 article page.</article>
</body></html>
"""

_ROLE_NAV_HTML = """
<html><body>
  <div role="navigation">
    <ul>
      <li><a href="https://docs.example.org/intro/">Intro</a></li>
      <li><a href="https://docs.example.org/setup/">Setup</a></li>
      <li><a href="https://docs.example.org/api/">API</a></li>
      <li><a href="https://docs.example.org/faq/">FAQ</a></li>
      <li><a href="https://docs.example.org/contact/">Contact</a></li>
    </ul>
  </div>
  <main><article>본문</article></main>
</body></html>
"""

_NO_SAME_HOST_HTML = """
<html><body>
  <main>
    <div class="results">
      <div class="r"><a href="https://ext1.com/a">External 1</a></div>
      <div class="r"><a href="https://ext2.com/b">External 2</a></div>
      <div class="r"><a href="https://ext3.com/c">External 3</a></div>
      <div class="r"><a href="https://ext4.com/d">External 4</a></div>
      <div class="r"><a href="https://ext5.com/e">External 5</a></div>
    </div>
  </main>
</body></html>
"""


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import all_same_host_patterns_in_nav, html_repeating_patterns

    cases: list[tuple[str, bool, str]] = []

    # 1. BOARD — main 안 list + nav 안 메뉴 동시. outside_nav ≥ 1 → board verdict.
    pats = html_repeating_patterns(_BOARD_MAIN_LIST_HTML, base_url="https://board.example.com/list")
    out = all_same_host_patterns_in_nav(html=_BOARD_MAIN_LIST_HTML, html_candidates=pats,
                                        base_url="https://board.example.com/list")
    cases.append(("board_main_list_passes",
                  out is not None and out["nav_only_same_host"] is False and out["outside_nav"] >= 1,
                  f"got {out!r}"))

    # 2. SINGLE ART — nav 안에만 same-host pattern. outside_nav == 0 → single-article verdict.
    pats = html_repeating_patterns(_NAV_ONLY_HTML, base_url="https://www.theholocaustexplained.org/x/")
    out = all_same_host_patterns_in_nav(html=_NAV_ONLY_HTML, html_candidates=pats,
                                        base_url="https://www.theholocaustexplained.org/x/")
    cases.append(("nav_only_single_article",
                  out is not None and out["nav_only_same_host"] is True and out["outside_nav"] == 0,
                  f"got {out!r}"))

    # 3. role=navigation 도 nav 신호로 인정.
    pats = html_repeating_patterns(_ROLE_NAV_HTML, base_url="https://docs.example.org/page/")
    out = all_same_host_patterns_in_nav(html=_ROLE_NAV_HTML, html_candidates=pats,
                                        base_url="https://docs.example.org/page/")
    cases.append(("role_navigation_counted",
                  out is not None and out["nav_only_same_host"] is True
                  and any("role=navigation" in s for s in (out.get("sample_nav_ancestors") or [])),
                  f"got {out!r}"))

    # 4. same-host pattern 0건 → None (판정 불가).
    pats = html_repeating_patterns(_NO_SAME_HOST_HTML, base_url="https://aggregator.example.com/search")
    out = all_same_host_patterns_in_nav(html=_NO_SAME_HOST_HTML, html_candidates=pats,
                                        base_url="https://aggregator.example.com/search")
    cases.append(("no_same_host_returns_none", out is None, f"got {out!r}"))

    # 5. 빈 html → None.
    out = all_same_host_patterns_in_nav(html="", html_candidates=[],
                                        base_url="https://example.com/")
    cases.append(("empty_html_returns_none", out is None, f"got {out!r}"))

    # 6. base_url 없음 → None.
    out = all_same_host_patterns_in_nav(html=_BOARD_MAIN_LIST_HTML, html_candidates=[{"selector": "li"}],
                                        base_url="")
    cases.append(("empty_base_url_returns_none", out is None, f"got {out!r}"))

    return cases
