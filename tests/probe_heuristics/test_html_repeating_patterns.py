"""probe.extract.html_repeating_patterns — 시그니처 그룹핑 + href 수집."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import html_repeating_patterns

    cases: list[tuple[str, bool, str]] = []

    # 1. 정적 글 목록 — ul.list > li.item × 6
    html = '<ul class="list">' + ''.join(
        f'<li class="item"><a href="/view/{i}">title {i}</a></li>'
        for i in range(1, 7)
    ) + '</ul>'
    out = html_repeating_patterns(html, "https://x.com/board")
    cases.append(("ul_li_x6", len(out) >= 1 and out[0]["child_count"] == 6,
                  f"got {len(out)} candidates"))
    if out:
        c = out[0]
        cases.append(("sample_url_absolute",
                      c["sample_url"] == "https://x.com/view/1",
                      f"got sample_url={c.get('sample_url')!r}"))
        cases.append(("href_pattern_guess",
                      c["href_pattern_guess"] == "/view/{n}",
                      f"got {c.get('href_pattern_guess')!r}"))
        cases.append(("common_prefix",
                      c["href_common_prefix"] == "/view/",
                      f"got {c.get('href_common_prefix')!r}"))

    # 2. javascript: href + data-id 속성 (post_id 가 data-* 에 있는 케이스)
    html = '<ul class="list">' + ''.join(
        f'<li class="item" data-id="{i}"><a href="javascript:goView({i})">t{i}</a></li>'
        for i in range(1, 7)
    ) + '</ul>'
    out = html_repeating_patterns(html, "https://x.com/board")
    cases.append(("js_href_detected", len(out) >= 1 and out[0].get("href_is_js") is True,
                  f"got {out!r}"))
    if out and out[0].get("row_data_attrs"):
        cases.append(("row_data_attrs_has_id",
                      "data-id" in (out[0]["row_data_attrs"] or {}),
                      f"got {out[0]['row_data_attrs']!r}"))

    # 3. min_children 미달 — 4개만
    html = '<ul>' + ''.join(f'<li class="x"><a href="/v/{i}">t</a></li>' for i in range(4)) + '</ul>'
    out = html_repeating_patterns(html, "https://x.com")
    cases.append(("too_few_children", len(out) == 0, f"got {len(out)} candidates"))

    # 4. 빈 HTML
    cases.append(("empty_html", html_repeating_patterns("", "https://x.com") == [], ""))

    return cases
