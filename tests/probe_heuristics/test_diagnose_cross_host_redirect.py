"""Cross-site redirects should be url_dead, not a viable list page."""
from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


covers = ["diagnose_cross_host_redirect"]


def _result(url: str, final_url: str | None, classification, *, status: int = 200):
    from probe.types import Result

    return Result(
        strategy="S1.H2",
        target="list",
        url=url,
        final_url=final_url,
        status=status,
        duration_ms=10,
        headers={},
        classification=classification,
        notable=[],
        error=None,
    )


def _diagnose(input_url: str, final_url: str):
    from probe.diagnose import diagnose
    from probe.types import Classification

    baseline = {
        "B1": _result(input_url, input_url, Classification.OK),
        "B2": _result(input_url, input_url, Classification.OK),
    }
    static_results = [
        _result(input_url, final_url, Classification.OK),
        _result(input_url, final_url, Classification.OK),
    ]
    with TemporaryDirectory() as tmp:
        list_candidates_path = Path(tmp) / "list_candidates.json"
        list_candidates_path.write_text("{}", encoding="utf-8")
        return diagnose(
            slug="test",
            url=input_url,
            baseline=baseline,
            static_results=static_results,
            headless=None,
            captured_retry=None,
            s1l=None,
            external_results=[],
            paid_results=[],
            list_candidates_path=list_candidates_path,
            article_result=None,
            robots_info={},
        )


def run() -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []

    d1 = _diagnose("https://slaythespire.com/news/", "https://megacrit.com/")
    cases.append(("cross_etld_redirect_gets_verdict",
                  "CROSS_HOST_REDIRECT" in d1.verdict,
                  d1.verdict))

    d2 = _diagnose("https://example.com/news/", "https://www.example.com/")
    cases.append(("www_redirect_same_etld_not_cross_host",
                  "CROSS_HOST_REDIRECT" not in d2.verdict,
                  d2.verdict))

    d3 = _diagnose("https://warthunder.com/", "https://warthunder.com/en")
    cases.append(("locale_path_same_host_not_cross_host",
                  "CROSS_HOST_REDIRECT" not in d3.verdict,
                  d3.verdict))

    d4 = _diagnose("https://starfield.bethesda.net/", "https://bethesda.net/game/starfield")
    cases.append(("subdomain_to_parent_same_etld_not_cross_host_for_now",
                  "CROSS_HOST_REDIRECT" not in d4.verdict,
                  d4.verdict))

    return cases


if __name__ == "__main__":
    failed = [(n, m) for n, ok, m in run() if not ok]
    if failed:
        raise SystemExit(failed)
