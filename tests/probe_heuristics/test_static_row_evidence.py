"""probe.diagnose static row evidence must come from static response bodies."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory


covers: list[str] = []


def _result(body_path: str):
    from probe.types import Classification, Result

    return Result(
        strategy="S1.H2",
        target="list",
        url="https://pubg.com/news/",
        final_url="https://pubg.com/en/news/",
        status=200,
        duration_ms=10,
        body_path=body_path,
        classification=Classification.OK,
    )


def run() -> list[tuple[str, bool, str]]:
    from probe.diagnose import _static_row_evidence

    cases: list[tuple[str, bool, str]] = []

    with TemporaryDirectory() as tmp_s:
        tmp = Path(tmp_s)
        static_placeholder = tmp / "static_placeholder.html"
        static_placeholder.write_text(
            "<main><section class='post-contents'>"
            + "".join(
                f"<div class='post-contents__card'><h2>Loading {i}</h2></div>"
                for i in range(17)
            )
            + "</section></main>",
            encoding="utf-8",
        )
        rendered_payload = {
            "first_article_url": "https://pubg.com/en/news/12345",
            "html_repeating_patterns": [
                {
                    "selector": "section.post-contents > div.post-contents__card",
                    "child_count": 17,
                    "first_text": "Loading 0",
                    "sample_url": None,
                }
            ],
        }
        evidence = _static_row_evidence([_result(str(static_placeholder))], rendered_payload)
        cases.append(("rejects_rendered_sample_url_without_static_href",
                      evidence is None,
                      f"got {json.dumps(evidence, ensure_ascii=False)}"))

        static_articles = tmp / "static_articles.html"
        static_articles.write_text(
            "<main><section class='post-contents'>"
            + "".join(
                f'''<a class="post-contents__card" href="/en/news/{10000 + i}">
                      <h2>News {i}</h2>
                    </a>'''
                for i in range(12)
            )
            + "</section></main>",
            encoding="utf-8",
        )
        static_payload = {
            "html_repeating_patterns": [
                {
                    "selector": "section.post-contents > a.post-contents__card",
                    "child_count": 12,
                    "first_text": "News 0",
                    "sample_url": "https://pubg.com/en/news/10000",
                }
            ],
        }
        evidence = _static_row_evidence([_result(str(static_articles))], static_payload)
        cases.append(("accepts_static_href_from_static_body",
                      evidence is not None
                      and evidence.get("sample_url") == "https://pubg.com/en/news/10000"
                      and evidence.get("child_count") == 12,
                      f"got {json.dumps(evidence, ensure_ascii=False)}"))

    return cases
