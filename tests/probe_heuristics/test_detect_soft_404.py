"""probe.extract.detect_soft_404 — HTTP 200 not-found shell 판정."""
from __future__ import annotations

covers = ["detect_soft_404"]


def run() -> list[tuple[str, bool, str]]:
    from pathlib import Path
    import tempfile

    from probe.diagnose import diagnose
    from probe.extract import detect_soft_404
    from probe.types import Classification, Result

    cases: list[tuple[str, bool, str]] = []

    html = """<html><head><title>Page Not Found</title></head>
      <body><main><h1>お探しのページは見つかりませんでした</h1></main></body></html>"""
    out = detect_soft_404(html, "https://www.tms-e.co.jp/news/")
    cases.append(("title_h1_soft_404", bool(out and out["is_soft_404"] and out["row_count"] <= 2), str(out)))

    board_rows = "<html><head><title>News</title></head><body><h1>News</h1><ul>" + "".join(
        f"<li class='post'><a href='/news/{i}'>Post {i}</a></li>" for i in range(8)
    ) + "</ul></body></html>"
    cases.append(("normal_board_no_match", detect_soft_404(board_rows, "https://example.com/news/") is None, ""))

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "list_candidates.json"
        p.write_text(
            '{"html_repeating_patterns":[],"traffic_json_api_candidates":[],'
            '"hydration_list_candidates":[],"first_article_url":null,'
            '"soft_404":{"is_soft_404":true,"signal":"title: Page Not Found","row_count":0}}',
            encoding="utf-8",
        )
        ok = Result(strategy="S1.H1", target="list", url="https://www.tms-e.co.jp/news/",
                    status=200, classification=Classification.OK, notable=[], body_path=None)
        d = diagnose(
            slug="host_tms-e_news",
            url="https://www.tms-e.co.jp/news/",
            baseline={"B1": ok},
            static_results=[ok],
            headless=None,
            captured_retry=None,
            s1l=None,
            external_results=[],
            paid_results=[],
            list_candidates_path=p,
            article_result=None,
            robots_info={},
        )
        cases.append(("diagnose_verdict_soft_404", d.verdict == "SOFT_404", d.verdict))

    cases.append(("empty_html_none", detect_soft_404("", "https://example.com/") is None, ""))
    return cases
