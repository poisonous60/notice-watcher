"""scripts.probe headless wall-clock guard."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    import sys
    import time
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

    from probe.types import Classification, Result
    from scripts.probe import _headless_timeout_result, _static_results_are_hard_login

    cases: list[tuple[str, bool, str]] = []

    hard_login = [
        Result(strategy="S1.H2", target="list", url="https://x.test/posts",
               classification=Classification.LOGIN_REQUIRED, notable=["redirected to login"]),
        Result(strategy="S1.H3", target="list", url="https://x.test/posts",
               classification=Classification.LOGIN_REQUIRED, notable=["redirected to login"]),
    ]
    cases.append(("hard_login_static_skips_headless",
                  _static_results_are_hard_login(hard_login) is True, "hard login not detected"))

    mixed_ok = hard_login + [
        Result(strategy="S1.H4", target="list", url="https://x.test/posts",
               classification=Classification.OK, notable=[]),
    ]
    cases.append(("ok_static_does_not_skip_headless",
                  _static_results_are_hard_login(mixed_ok) is False, "OK result should keep headless enabled"))

    timeout = _headless_timeout_result(
        url="https://x.test/posts",
        target="list",
        started=time.perf_counter(),
        cap_s=45,
    )
    cases.append(("timeout_degrades_unknown_error",
                  timeout.classification == Classification.UNKNOWN_ERROR
                  and timeout.strategy == "S4"
                  and "headless_timeout" in (timeout.error or ""),
                  f"got {timeout}"))

    click_timeout = _headless_timeout_result(
        url="https://x.test/posts",
        target="article_click",
        started=time.perf_counter(),
        cap_s=45,
    )
    cases.append(("click_timeout_uses_article_strategy",
                  click_timeout.target == "article" and click_timeout.strategy == "S4.click",
                  f"got target={click_timeout.target} strategy={click_timeout.strategy}"))

    return cases


if __name__ == "__main__":
    failed = [(n, m) for n, ok, m in run() if not ok]
    if failed:
        raise SystemExit(failed)
