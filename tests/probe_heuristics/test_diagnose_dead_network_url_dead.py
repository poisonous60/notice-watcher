"""Dead network baseline should produce register url_dead verdict."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

    from probe.diagnose import diagnose
    from probe.types import Classification, Result

    def _dead_result(strategy: str, target: str, url: str) -> Result:
        return Result(
            strategy=strategy,
            target=target,
            url=url,
            status=None,
            classification=Classification.UNKNOWN_ERROR,
            error="ConnectError: [WinError 10061] connection refused",
            notable=["error: ConnectError: [WinError 10061] connection refused"],
        )

    url = "http://127.0.0.1:9/news"
    baseline = {
        "B1": _dead_result("B1", "baseline", "http://127.0.0.1:9/"),
        "B2": _dead_result("B2", "baseline", "http://127.0.0.1:9/robots.txt"),
    }
    static_results = [
        _dead_result("S1.H2", "list", url),
        _dead_result("S1.H3", "list", url),
        _dead_result("S1.H4", "list", url),
    ]
    diagnosis = diagnose(
        slug="host_127-0-0-1_9_news",
        url=url,
        baseline=baseline,
        static_results=static_results,
        headless=None,
        captured_retry=None,
        s1l=None,
        external_results=[],
        paid_results=[],
        list_candidates_path=Path("output/does-not-exist/list_candidates.json"),
        article_result=None,
        robots_info={},
    )

    return [
        (
            "dead_network_baseline_is_url_dead",
            "CERT_OR_DNS_BROKEN" in diagnosis.verdict,
            f"verdict={diagnosis.verdict!r}",
        )
    ]


if __name__ == "__main__":
    failed = [(n, m) for n, ok, m in run() if not ok]
    if failed:
        raise SystemExit(failed)
