"""probe.extract._href_pattern — 첫 href 의 숫자를 {n} 으로 치환."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import _href_pattern

    cases: list[tuple[str, bool, str]] = []

    # 1. path 끝 숫자
    out = _href_pattern(["/view/12345"])
    cases.append(("path_tail_number", out == "/view/{n}", f"got {out!r}"))

    # 2. path 중간 숫자 + 트레일 슬래시
    out = _href_pattern(["/board/notice/12345/"])
    cases.append(("path_mid_number_trailing_slash", out == "/board/notice/{n}/", f"got {out!r}"))

    # 3. 쿼리스트링 숫자
    out = _href_pattern(["/notice.do?mode=view&id=12345"])
    cases.append(("query_number", out == "/notice.do?mode=view&id={n}", f"got {out!r}"))

    # 4. 빈 리스트
    out = _href_pattern([])
    cases.append(("empty", out is None, f"got {out!r}"))

    # 5. 숫자 없는 href
    out = _href_pattern(["/about/contact"])
    cases.append(("no_number", out == "/about/contact", f"got {out!r}"))

    return cases
