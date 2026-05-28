"""probe.diagnose downgrades static OK verdict for JS hydration placeholders."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory


covers: list[str] = []


def _result(strategy: str, classification, *, body_path: str | None = None):
    from probe.types import Result

    return Result(
        strategy=strategy,
        target="list",
        url="https://pubg.com/news/",
        final_url="https://pubg.com/en/news/",
        status=200,
        duration_ms=10,
        body_path=body_path,
        classification=classification,
        notable=[],
    )


def _diagnose(tmp: Path, *, static_html: str, rendered_html: str, first_article_url: str):
    from probe.diagnose import diagnose
    from probe.types import Classification, Result

    static_body = tmp / "static.html"
    rendered_body = tmp / "rendered.html"
    list_candidates = tmp / "list_candidates.json"
    static_body.write_text(static_html, encoding="utf-8")
    rendered_body.write_text(rendered_html, encoding="utf-8")
    list_candidates.write_text(json.dumps({
        "first_article_url": first_article_url,
        "html_repeating_patterns": [
            {
                "selector": "section.post-contents > div.post-contents__card",
                "child_count": 17,
                "sample_url": first_article_url,
            }
        ],
        "traffic_json_api_candidates": [],
        "hydration_list_candidates": [],
    }), encoding="utf-8")

    baseline = {
        "B1": Result(
            strategy="B1",
            target="baseline",
            url="https://pubg.com/",
            status=200,
            classification=Classification.OK,
        )
    }
    return diagnose(
        slug="host_pubg-com_news_17f4ebc1",
        url="https://pubg.com/news/",
        baseline=baseline,
        static_results=[_result("S1.H2", Classification.OK, body_path=str(static_body))],
        headless=_result("S4", Classification.OK, body_path=str(rendered_body)),
        captured_retry=None,
        s1l=None,
        external_results=[],
        paid_results=[],
        list_candidates_path=list_candidates,
        article_result=None,
        robots_info={},
    )


def run() -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []
    hydration_prefix = "정적 응답이 hydration placeholder"

    with TemporaryDirectory() as tmp_s:
        tmp = Path(tmp_s)
        first_url = "https://pubg.com/en/news/12345"
        placeholder_static = (
            "<html><body><main><section class='post-contents'>"
            + "".join(
                f"<div class='post-contents__card'><h2>Loading {i}</h2></div>"
                for i in range(17)
            )
            + "</section></main></body></html>"
        )
        rendered = (
            "<html><body><main><section class='post-contents'>"
            + "".join(
                f"<div class='post-contents__card'><a href='/en/news/{12345 + i}'>News {i}</a></div>"
                for i in range(10)
            )
            + "</section></main></body></html>"
        )
        d = _diagnose(tmp, static_html=placeholder_static, rendered_html=rendered, first_article_url=first_url)
        cases.append((
            "hydration_placeholder_downgrades_static_verdict",
            "JS 실행 필요" in d.verdict and "정적 HTTP로 충분" not in d.verdict,
            f"verdict={d.verdict!r}",
        ))
        cases.append((
            "hydration_placeholder_note_uses_stable_prefix",
            any(hydration_prefix in n for n in d.notes),
            f"notes={d.notes!r}",
        ))
        cases.append((
            "hydration_placeholder_recommends_playwright",
            "Playwright" in d.recommended_strategy,
            f"recommended={d.recommended_strategy!r}",
        ))

    with TemporaryDirectory() as tmp_s:
        tmp = Path(tmp_s)
        first_url = "https://pubg.com/en/news/12345"
        static_ssr = (
            "<html><body><main><section class='post-contents'>"
            + "".join(
                f"<div class='post-contents__card'><a href='/en/news/{12345 + i}'>News {i}</a></div>"
                for i in range(17)
            )
            + "</section></main></body></html>"
        )
        rendered = static_ssr
        d = _diagnose(tmp, static_html=static_ssr, rendered_html=rendered, first_article_url=first_url)
        cases.append((
            "ssr_static_anchor_keeps_static_verdict",
            "정적 HTTP로 충분" in d.verdict and "JS 실행 필요" not in d.verdict,
            f"verdict={d.verdict!r}",
        ))
        cases.append((
            "ssr_static_anchor_does_not_emit_hydration_note",
            not any(hydration_prefix in n for n in d.notes),
            f"notes={d.notes!r}",
        ))

    return cases
