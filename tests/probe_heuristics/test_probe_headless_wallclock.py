"""scripts.probe headless wall-clock guard."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    import sys
    import time
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

    from probe.types import Classification, Result
    import scripts.probe as probe_script
    from scripts.probe import (
        _headless_timeout_result,
        _static_registered_domain,
        _static_result_for_headless_skip,
        _static_result_allows_headless_skip,
        _static_results_are_hard_login,
    )

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

    tmp = Path(__file__).resolve().parents[2] / "output" / "tmp_test_static_headless_skip.html"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(
        "<html><body><main>"
        + "".join(
            f"<article class='post'><a href='/news/{i}'>Post {i}</a><time>2026-05-{i:02d}</time></article>"
            for i in range(1, 8)
        )
        + "</main></body></html>",
        encoding="utf-8",
    )
    static_ok = [
        Result(strategy="S1.H2", target="list", url="https://x.test/news",
               status=200, classification=Classification.OK, body_path=str(tmp), notable=[]),
    ]
    cases.append(("static_rows_allow_headless_skip",
                  _static_result_allows_headless_skip(static_ok, url="https://x.test/news") is True,
                  "static HTML with repeated article links should skip Phase 2"))

    old_static_skip = probe_script.STATIC_OK_HEADLESS_SKIP
    try:
        probe_script.STATIC_OK_HEADLESS_SKIP = False
        cases.append(("static_skip_env_disabled_returns_none",
                      _static_result_for_headless_skip(static_ok, url="https://x.test/news") is None,
                      "disabled static skip must return None, not falsey non-None"))
    finally:
        probe_script.STATIC_OK_HEADLESS_SKIP = old_static_skip

    empty_tmp = Path(__file__).resolve().parents[2] / "output" / "tmp_test_static_headless_skip_empty.html"
    empty_tmp.write_text("<html><body><main><p>No rows here.</p></main></body></html>", encoding="utf-8")
    mixed_static_ok = [
        Result(strategy="S1.H2", target="list", url="https://x.test/news",
               status=200, classification=Classification.OK, body_path=str(empty_tmp), notable=[]),
        Result(strategy="S1.H3", target="list", url="https://x.test/news",
               status=200, classification=Classification.OK, body_path=str(tmp), notable=[]),
    ]
    cases.append(("static_skip_returns_skipworthy_result",
                  (_static_result_for_headless_skip(mixed_static_ok, url="https://x.test/news") or object())
                  is mixed_static_ok[1],
                  "skip must preserve the same static body used for candidate extraction"))

    nav_tmp = Path(__file__).resolve().parents[2] / "output" / "tmp_test_static_headless_skip_nav.html"
    nav_tmp.write_text(
        "<html><body><header><nav><ul>"
        + "".join(f"<li><a href='/category/{i}'>Category {i}</a></li>" for i in range(1, 8))
        + "</ul></nav></header><main><p>loading...</p></main></body></html>",
        encoding="utf-8",
    )
    nav_static_ok = [
        Result(strategy="S1.H2", target="list", url="https://x.test/news",
               status=200, classification=Classification.OK, body_path=str(nav_tmp), notable=[]),
    ]
    cases.append(("static_nav_rows_do_not_allow_headless_skip",
                  _static_result_allows_headless_skip(nav_static_ok, url="https://x.test/news") is False,
                  "nav/category lists must not skip Phase 2"))

    nav_internal_tmp = Path(__file__).resolve().parents[2] / "output" / "tmp_test_static_headless_skip_nav_internal.html"
    nav_internal_tmp.write_text(
        "<html><body><header><nav><ul>"
        + "".join(f"<li><a href='/news/{i}'>Internal {i}</a></li>" for i in range(1, 8))
        + "</ul></nav></header><main><p>loading...</p></main></body></html>",
        encoding="utf-8",
    )
    nav_internal_static_ok = [
        Result(strategy="S1.H2", target="list", url="https://x.test/news",
               status=200, classification=Classification.OK, body_path=str(nav_internal_tmp), notable=[]),
    ]
    cases.append(("static_nav_selector_space_does_not_allow_headless_skip",
                  _static_result_allows_headless_skip(nav_internal_static_ok, url="https://x.test/news") is False,
                  "nav selectors with spaces must not skip Phase 2"))

    query_tmp = Path(__file__).resolve().parents[2] / "output" / "tmp_test_static_headless_skip_query.html"
    query_tmp.write_text(
        "<html><body><main>"
        + "".join(
            f"<article><a href='/board.php?category=notice&page={i}'>Notice category {i}</a></article>"
            for i in range(1, 8)
        )
        + "</main></body></html>",
        encoding="utf-8",
    )
    query_static_ok = [
        Result(strategy="S1.H2", target="list", url="https://x.test/news",
               status=200, classification=Classification.OK, body_path=str(query_tmp), notable=[]),
    ]
    cases.append(("static_query_category_rows_do_not_allow_headless_skip",
                  _static_result_allows_headless_skip(query_static_ok, url="https://x.test/news") is False,
                  "category/search query rows must not skip Phase 2"))

    au_tmp = Path(__file__).resolve().parents[2] / "output" / "tmp_test_static_headless_skip_com_au.html"
    au_tmp.write_text(
        "<html><body><main>"
        + "".join(
            f"<article><a href='https://other.com.au/news/{i}'>External {i}</a></article>"
            for i in range(1, 8)
        )
        + "</main></body></html>",
        encoding="utf-8",
    )
    au_static_ok = [
        Result(strategy="S1.H2", target="list", url="https://example.com.au/news",
               status=200, classification=Classification.OK, body_path=str(au_tmp), notable=[]),
    ]
    cases.append(("static_com_au_external_rows_do_not_allow_headless_skip",
                  _static_result_allows_headless_skip(au_static_ok, url="https://example.com.au/news") is False,
                  "unrelated .com.au hosts must not be treated as same-site"))
    cases.append(("static_registered_domain_handles_com_au_without_tldextract",
                  _static_registered_domain("other.com.au") == "other.com.au",
                  "multi-label public suffix fallback must keep .com.au registrable domain"))

    ext_tmp = Path(__file__).resolve().parents[2] / "output" / "tmp_test_static_headless_skip_ext.html"
    ext_tmp.write_text(
        "<html><body><main>"
        + "".join(f"<article><a href='/category.php?page={i}'>Category page {i}</a></article>" for i in range(1, 8))
        + "</main></body></html>",
        encoding="utf-8",
    )
    ext_static_ok = [
        Result(strategy="S1.H2", target="list", url="https://x.test/news",
               status=200, classification=Classification.OK, body_path=str(ext_tmp), notable=[]),
    ]
    cases.append(("static_extension_category_rows_do_not_allow_headless_skip",
                  _static_result_allows_headless_skip(ext_static_ok, url="https://x.test/news") is False,
                  "extension-style category/search/login paths must not skip Phase 2"))

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
