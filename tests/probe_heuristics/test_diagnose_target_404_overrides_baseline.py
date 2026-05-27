"""baseline blocked + target HTTP 404 → url_dead (TARGET_NOT_FOUND), not cap_blocked.

vampire-survivors.com/news case: root → poncle.uk anti-bot (baseline_bot_only=True →
BASELINE_BLOCKED verdict) but /news = HTTP 404 직접 → 404 신호가 cap_blocked 분류를
이기고 url_dead 로 가야 함.
"""
from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


covers = ["diagnose_target_404_overrides_baseline_blocked"]


def _result(url: str, classification, *, status: int = 200):
    from probe.types import Result

    return Result(
        strategy="S1.H2",
        target="list",
        url=url,
        status=status,
        duration_ms=10,
        headers={},
        classification=classification,
        notable=[],
        error=None,
    )


def _diagnose(input_url: str, baseline_cls, target_cls, *, target_status=200):
    from probe.diagnose import diagnose

    baseline = {
        "B1": _result(input_url, baseline_cls),
        "B2": _result(input_url, baseline_cls),
    }
    static_results = [
        _result(input_url, target_cls, status=target_status),
        _result(input_url, target_cls, status=target_status),
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
    from probe.types import Classification

    cases: list[tuple[str, bool, str]] = []

    # baseline_bot_only (anti-bot 루트) + target 404 → TARGET_NOT_FOUND 박혀야 (cap_blocked 아님)
    d1 = _diagnose(
        "https://vampire-survivors.com/news/",
        Classification.BLOCKED_BOT,
        Classification.NOT_FOUND,
        target_status=404,
    )
    cases.append(
        (
            "baseline_bot_only_plus_target_404_gives_target_not_found",
            "TARGET_NOT_FOUND" in d1.verdict,
            d1.verdict,
        )
    )

    # baseline_ok + target 404 → 기존 동작 그대로 TARGET_NOT_FOUND
    d2 = _diagnose(
        "https://example.com/missing/",
        Classification.OK,
        Classification.NOT_FOUND,
        target_status=404,
    )
    cases.append(
        (
            "baseline_ok_plus_target_404_keeps_target_not_found",
            "TARGET_NOT_FOUND" in d2.verdict,
            d2.verdict,
        )
    )

    # baseline_bot_only + target OK → 기존 BASELINE_BLOCKED 류 유지 (TARGET_NOT_FOUND 없어야)
    d3 = _diagnose(
        "https://example.com/news/",
        Classification.BLOCKED_BOT,
        Classification.OK,
    )
    cases.append(
        (
            "baseline_bot_only_plus_target_ok_no_target_not_found",
            "TARGET_NOT_FOUND" not in d3.verdict,
            d3.verdict,
        )
    )

    return cases


if __name__ == "__main__":
    failed = [(n, m) for n, ok, m in run() if not ok]
    if failed:
        raise SystemExit(failed)
