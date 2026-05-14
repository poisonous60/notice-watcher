"""probe.extract.pick_first_article_url — 글 URL 후보들에서 1개 선정."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import pick_first_article_url

    cases: list[tuple[str, bool, str]] = []

    # 1. 정상 케이스 — 같은 호스트 + 글 ID 가 있는 sample_url
    html_cands = [
        {"sample_url": "https://x.com/login", "href_is_js": None},
        {"sample_url": "https://x.com/board/view/12345", "href_is_js": None},
    ]
    out = pick_first_article_url(
        html_candidates=html_cands,
        json_api_candidates=[],
        hydration_candidates=[],
        base_url="https://x.com/board",
        page_html="",
    )
    cases.append(("picks_view_over_login",
                  out == "https://x.com/board/view/12345", f"got {out!r}"))

    # 2. js_href 인 후보는 제외 (href_is_js=True)
    html_cands = [
        {"sample_url": None, "href_is_js": True},
        {"sample_url": "https://x.com/article/9999", "href_is_js": None},
    ]
    out = pick_first_article_url(
        html_candidates=html_cands,
        json_api_candidates=[],
        hydration_candidates=[],
        base_url="https://x.com/",
        page_html="",
    )
    cases.append(("skips_js_href", out == "https://x.com/article/9999", f"got {out!r}"))

    # 3. HTML 후보 0 + hydration 후보 1
    hyd = [{"sample_first": {"slug": "my-post"}}]
    out = pick_first_article_url(
        html_candidates=[],
        json_api_candidates=[],
        hydration_candidates=hyd,
        base_url="https://x.com/blog/",
        page_html="<html></html>",
    )
    cases.append(("hydration_slug_joined",
                  out == "https://x.com/blog/my-post", f"got {out!r}"))

    # 4. 후보 전부 없음 → None
    out = pick_first_article_url(
        html_candidates=[],
        json_api_candidates=[],
        hydration_candidates=[],
        base_url="https://x.com/",
        page_html="",
    )
    cases.append(("empty_candidates_none", out is None, f"got {out!r}"))

    return cases
