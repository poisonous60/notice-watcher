"""probe.diagnose should not recommend S1.Hcap when it is also an empty shell."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory


covers = ["diagnose_static_hcap_shell_contradiction"]


def _result(strategy: str, body_path: str | None = None):
    from probe.types import Classification, Result

    return Result(
        strategy=strategy,
        target="list",
        url="https://www.gamecity.ne.jp/news/",
        status=200,
        duration_ms=10,
        body_path=body_path,
        classification=Classification.OK,
    )


def run() -> list[tuple[str, bool, str]]:
    from probe.diagnose import diagnose
    from probe.types import Classification, Result

    cases: list[tuple[str, bool, str]] = []

    with TemporaryDirectory() as tmp_s:
        tmp = Path(tmp_s)
        static_shell = tmp / "static.html"
        captured_shell = tmp / "hcap.html"
        rendered = tmp / "rendered.html"
        list_candidates = tmp / "list_candidates.json"

        shell = "<html><body><div id='ajax_news'></div><a href='/privacy'>privacy</a></body></html>"
        full = (
            "<html><body><div id='ajax_news'>"
            + "".join(
                f"<a class='news-news-list__item' href='/news/{28000 + i}.html' data-id='{i}'>"
                f"NEWS {i} 2026/05/{(i % 28) + 1:02d}</a>"
                for i in range(40)
            )
            + "</div></body></html>"
        )
        static_shell.write_text(shell, encoding="utf-8")
        captured_shell.write_text(shell, encoding="utf-8")
        rendered.write_text(full, encoding="utf-8")
        list_candidates.write_text("{}", encoding="utf-8")

        baseline = {
            "B1": Result(
                strategy="B1",
                target="baseline",
                url="https://www.gamecity.ne.jp/",
                status=200,
                classification=Classification.OK,
            )
        }
        d = diagnose(
            slug="host_gamecity-ne-jp_news_ce778383",
            url="https://www.gamecity.ne.jp/news/",
            baseline=baseline,
            static_results=[_result("S1.H2", str(static_shell))],
            headless=_result("S4", str(rendered)),
            captured_retry=_result("S1.Hcap", str(captured_shell)),
            s1l=None,
            external_results=[],
            paid_results=[],
            list_candidates_path=list_candidates,
            article_result=None,
            robots_info={},
        )

    cases.append((
        "empty_hcap_does_not_win_recommended_strategy",
        "Playwright" in d.recommended_strategy and "S1.Hcap" not in d.recommended_strategy,
        f"recommended={d.recommended_strategy!r}",
    ))
    cases.append((
        "empty_hcap_does_not_win_verdict",
        "JS 실행 필요" in d.verdict and "캡처 헤더" not in d.verdict,
        f"verdict={d.verdict!r}",
    ))
    cases.append((
        "blank_shell_note_kept",
        any("정적 응답이 빈 shell" in n for n in d.notes),
        str(d.notes),
    ))
    return cases
