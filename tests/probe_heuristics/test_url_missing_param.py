"""KR egov URL family missing-param probe hints."""
from __future__ import annotations


covers = ["detect_url_missing_param_pattern"]


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import detect_url_missing_param_pattern

    cases: list[tuple[str, bool, str]] = []

    html = """
    <html><body>
      <script>alert('권한이 없습니다'); location.href='/main.do';</script>
      <a href="/site/bbs/list.do?bbsId=BBSMSTR_000000000001&menuid=148006001">공지</a>
      <a href="/site/bbs/list.do?bbsId=BBSMSTR_000000000001&menuid=148006001&pageIndex=2">2</a>
    </body></html>
    """
    hit = detect_url_missing_param_pattern(
        html,
        base_url="https://example.go.kr/site/bbs/list.do?bbsId=BBSMSTR_000000000001",
        html_candidates=[],
    )
    cases.append(("auth_redirect_suggests_menuid",
                  hit is not None and hit.get("symptom") == "auth_redirect"
                  and hit.get("suggested_param") == "menuid",
                  f"got {hit!r}"))

    shell = """
    <html><body>
      <p>게시판을 선택해 주세요.</p>
      <table><tbody></tbody></table>
      <a href="/board/list.do?boardId=notice&menuCd=DOM_0001">공지사항</a>
    </body></html>
    """
    hit2 = detect_url_missing_param_pattern(
        shell,
        base_url="https://example.or.kr/board/list.do?boardId=notice",
        html_candidates=[],
    )
    cases.append(("empty_shell_suggests_menuCd",
                  hit2 is not None and hit2.get("symptom") == "empty_shell"
                  and hit2.get("suggested_param") == "menuCd",
                  f"got {hit2!r}"))

    no_hit = detect_url_missing_param_pattern(
        '<html><body><table><tr><td><a href="/view.do?no=1">글</a></td></tr></table></body></html>',
        base_url="https://example.or.kr/board/list.do?boardId=notice",
        html_candidates=[{"child_count": 5, "sample_url": "https://example.or.kr/view.do?no=1"}],
    )
    cases.append(("real_rows_do_not_suggest", no_hit is None, f"got {no_hit!r}"))
    return cases

