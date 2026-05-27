"""probe.diagnose should trust strong static row evidence over Playwright hints."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory


covers = ["diagnose_static_rows_prefer_httpx"]


def _result(strategy: str, classification, *, body_path: str | None = None, status: int = 200, error: str | None = None):
    from probe.types import Result

    return Result(
        strategy=strategy,
        target="list",
        url="https://another-eden.jp/news/",
        status=status,
        duration_ms=10,
        body_path=body_path,
        classification=classification,
        notable=[],
        error=error,
    )


def run() -> list[tuple[str, bool, str]]:
    from probe.diagnose import diagnose
    from probe.types import Classification

    cases: list[tuple[str, bool, str]] = []

    with TemporaryDirectory() as tmp_s:
        tmp = Path(tmp_s)
        static_body = tmp / "static.html"
        headless_body = tmp / "headless.html"
        list_candidates = tmp / "list_candidates.json"

        static_body.write_text(
            "<html><body><ul id='backnumber'>"
            + "".join(f"<li><a href='/news/{i}/'>news {i}</a></li>" for i in range(116))
            + "</ul></body></html>",
            encoding="utf-8",
        )
        headless_body.write_text(
            "<html><body><ul id='backnumber'>"
            + "".join(f"<li><a href='/news/{i}/'>news {i}</a></li>" for i in range(116))
            + "</ul><section>"
            + "".join(f"<a class='sns' href='/share/{i}'>share</a>" for i in range(260))
            + "</section></body></html>",
            encoding="utf-8",
        )
        list_candidates.write_text(json.dumps({
            "first_article_url": "https://another-eden.jp/news/1/",
            "html_repeating_patterns": [
                {
                    "selector": "#backnumber > li",
                    "child_count": 116,
                    "sample_url": "https://another-eden.jp/news/1/",
                    "href_pattern_guess": "/news/{id}/",
                }
            ],
            "traffic_json_api_candidates": [],
            "hydration_list_candidates": [],
        }), encoding="utf-8")

        baseline = {
            "B1": _result("B1", Classification.OK),
        }
        d = diagnose(
            slug="host_another-eden-jp_news_57af7bcf",
            url="https://another-eden.jp/news/",
            baseline=baseline,
            static_results=[_result("S1.H2", Classification.OK, body_path=str(static_body))],
            headless=_result("S4", Classification.OK, body_path=str(headless_body)),
            captured_retry=None,
            s1l=None,
            external_results=[],
            paid_results=[],
            list_candidates_path=list_candidates,
            article_result=None,
            robots_info={},
        )

    cases.append(("static_rows_keep_httpx_recommendation",
                  d.recommended_strategy.startswith("httpx (S1."),
                  f"recommended={d.recommended_strategy!r}"))
    cases.append(("static_rows_do_not_emit_js_required_verdict",
                  "JS 실행 필요" not in d.verdict,
                  f"verdict={d.verdict!r}"))
    cases.append(("static_rows_note_present",
                  any("정적 HTML row" in n for n in d.notes),
                  f"notes={d.notes!r}"))

    return cases
