"""_static_results_are_uniformly_dead behavior."""
from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from probe.types import Classification, Result
from scripts.probe import _static_results_are_uniformly_dead


def _result(status: int | None, classification: Classification) -> Result:
    return Result(
        strategy="S1.H2",
        target="list",
        url="https://example.test/news",
        status=status,
        classification=classification,
    )


def run() -> list[tuple[str, bool, str]]:
    cases = [
        ("all_200", [_result(200, Classification.OK)], False),
        ("all_404", [_result(404, Classification.NOT_FOUND)], True),
        ("all_503", [_result(503, Classification.UNKNOWN_ERROR)], True),
        ("all_connect_err_none", [_result(None, Classification.UNKNOWN_ERROR)], True),
        ("all_connect_err_zero", [_result(0, Classification.UNKNOWN_ERROR)], True),
        ("mixed_404_and_200", [_result(404, Classification.NOT_FOUND), _result(200, Classification.OK)], False),
        ("all_login", [_result(200, Classification.LOGIN_REQUIRED)], False),
        ("empty", [], False),
        ("200_and_503", [_result(200, Classification.OK), _result(503, Classification.UNKNOWN_ERROR)], False),
        ("403_and_404", [_result(403, Classification.BLOCKED_BOT), _result(404, Classification.NOT_FOUND)], True),
    ]

    results: list[tuple[str, bool, str]] = []
    for name, results_list, expected in cases:
        actual = _static_results_are_uniformly_dead(results_list)
        results.append((name, actual == expected, f"expected={expected} actual={actual}"))
    return results


if __name__ == "__main__":
    failed = False
    for name, ok, msg in run():
        print(f"{'PASS' if ok else 'FAIL'}  {name}  {msg}")
        failed = failed or not ok
    raise SystemExit(1 if failed else 0)
