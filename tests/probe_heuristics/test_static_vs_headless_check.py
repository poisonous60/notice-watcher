"""static_vs_headless_check 휴리스틱 fixture.

정적 응답 vs Playwright 응답 콘텐츠 비교 — *정적이 충분한지* 검증.
probe/diagnose.py 가 verdict "정적 HTTP로 충분" 박을 때 이 신호로 정정.
"""
from __future__ import annotations

from probe.extract import static_vs_headless_check


def run() -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []

    # 1) piku-like — 정적은 짧고 row 없음, Playwright 는 길고 data-id/anchor 다수.
    static_shell = "<html><head><title>x</title></head><body><div>shell only</div></body></html>"
    pw_full = ("<html><head><title>x</title></head><body>"
               + "".join(
                   f'<div data-id="{i}"><a href="/w/{i}">go</a>'
                   f' lorem ipsum padding text padding text padding text padding text padding</div>'
                   for i in range(40)
               )
               + "</body></html>")
    out = static_vs_headless_check(static_shell, pw_full)
    cases.append((
        "piku_like_insufficient_detected",
        out.get("static_insufficient") is True
        and out.get("ratio") >= 2.0
        and out.get("row_signal_headless") - out.get("row_signal_static") >= 5,
        f"out={out}",
    ))

    # 2) 정적 = headless — 같은 콘텐츠. static_insufficient=False (정적 충분).
    same_html = ("<html><body>" + "".join(f'<a href="/p/{i}">post {i}</a>' for i in range(20))
                 + "</body></html>")
    out = static_vs_headless_check(same_html, same_html)
    cases.append((
        "same_content_sufficient",
        out.get("static_insufficient") is False
        and out.get("ratio") == 1.0,
        f"out={out}",
    ))

    # 3) headless 가 정적의 1.5배 (ratio 부족) → static_insufficient=False.
    static_some = ("<html><body>" + "".join(f'<a href="/p/{i}">post {i}</a>' for i in range(20))
                   + "</body></html>")
    pw_more = ("<html><body>" + "".join(f'<a href="/p/{i}">post {i} extra padding</a>' for i in range(20))
               + "</body></html>")
    out = static_vs_headless_check(static_some, pw_more)
    cases.append((
        "small_ratio_not_insufficient",
        out.get("static_insufficient") is False,
        f"out={out}",
    ))

    # 4) headless 가 2배 이상 크지만 row-like 신호 차이 작음 (광고/footer 만 추가) → static_insufficient=False.
    static_with_rows = ("<html><body>"
                        + "".join(f'<a href="/p/{i}">x</a>' for i in range(10))
                        + "</body></html>")
    pw_padding_only = ("<html><body>"
                       + "".join(f'<a href="/p/{i}">x</a>' for i in range(11))
                       + "<footer>" + "padding " * 500 + "</footer></body></html>")
    out = static_vs_headless_check(static_with_rows, pw_padding_only)
    cases.append((
        "padding_only_not_insufficient",
        out.get("static_insufficient") is False,
        f"out={out}",
    ))

    # 5) None / 빈 문자열 입력 → 안전 (static_insufficient=False, ratio=0.0).
    out = static_vs_headless_check(None, "<html></html>")
    cases.append((
        "none_input_safe",
        out.get("static_insufficient") is False and out.get("ratio") == 0.0,
        f"out={out}",
    ))
    out = static_vs_headless_check("", "")
    cases.append((
        "empty_strings_safe",
        out.get("static_insufficient") is False and out.get("ratio") == 0.0,
        f"out={out}",
    ))

    return cases
