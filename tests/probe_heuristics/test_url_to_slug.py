"""probe.paths.url_to_slug — URL → slug 변환 (디렉토리명 결정)."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from probe.paths import url_to_slug

    cases: list[tuple[str, bool, str]] = []

    # 1. 단순 host + path
    out = url_to_slug("https://x.com/board")
    cases.append(("simple", out == "x.com_board", f"got {out!r}"))

    # 2. 쿼리스트링 포함
    out = url_to_slug("https://cse.skku.edu/cse/notice.do?mode=list&srCategoryId1=1582")
    cases.append(("with_query",
                  out == "cse.skku.edu_cse_notice.do_mode_list_srCategoryId1_1582",
                  f"got {out!r}"))

    # 3. trailing slash
    out_a = url_to_slug("https://x.com/board/")
    out_b = url_to_slug("https://x.com/board")
    cases.append(("trailing_slash_normalized", out_a == out_b, f"a={out_a!r}, b={out_b!r}"))

    # 4. https vs http 같음
    out_a = url_to_slug("https://x.com/a")
    out_b = url_to_slug("http://x.com/a")
    cases.append(("scheme_ignored", out_a == out_b, f"https={out_a!r}, http={out_b!r}"))

    # 5. 안정성 — 같은 입력 = 같은 출력
    u = "https://endfield.gryphline.com/ko-kr/news"
    cases.append(("deterministic", url_to_slug(u) == url_to_slug(u), ""))

    return cases
