"""probe.diagnose — list 진입 LOGIN_REQUIRED → LOGIN_REDIRECT(hard) / LOGIN_MARKER(soft) verdict.

ADR 0007 §확장(2026-05-22): login 신호를 verdict 로 surface (이전엔 verdict 에 안 실렸음 → register 死배선).
notable 의 "redirected to login"(경로1=redirect) 이면 hard, 본문 마커/form(경로2~4) 이면 soft.
"""
from __future__ import annotations

covers = ["diagnose"]


def run() -> list[tuple[str, bool, str]]:
    from pathlib import Path
    import tempfile

    from probe.diagnose import diagnose
    from probe.types import Classification, Result

    cases: list[tuple[str, bool, str]] = []

    def _diag(list_results, base_ok=True):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "list_candidates.json"
            p.write_text('{"html_repeating_patterns":[],"traffic_json_api_candidates":[],'
                         '"hydration_list_candidates":[],"first_article_url":null}', encoding="utf-8")
            base = Result(strategy="B1", target="list", url="https://x.org/board",
                          status=200, classification=Classification.OK if base_ok else Classification.BLOCKED_BOT,
                          notable=[], body_path=None)
            return diagnose(
                slug="host_x_board", url="https://x.org/board",
                baseline={"B1": base}, static_results=list_results,
                headless=None, captured_retry=None, s1l=None,
                external_results=[], paid_results=[],
                list_candidates_path=p, article_result=None, robots_info={},
            )

    def _login(notable):
        return Result(strategy="S1.H1", target="list", url="https://x.org/board",
                      status=200, classification=Classification.LOGIN_REQUIRED,
                      notable=notable, body_path=None)

    # 1. redirect → LOGIN_REDIRECT (hard)
    d = _diag([_login(["redirected to login"])])
    cases.append(("login_redirect", "LOGIN_REDIRECT" in d.verdict, d.verdict))

    # 2. 본문 마커 → LOGIN_MARKER (soft)
    d = _diag([_login(["weak login marker + short body"])])
    cases.append(("login_marker_weak", "LOGIN_MARKER" in d.verdict, d.verdict))

    # 3. login form → LOGIN_MARKER (soft)
    d = _diag([_login(["login form + short body"])])
    cases.append(("login_marker_form", "LOGIN_MARKER" in d.verdict, d.verdict))

    # 4. OK list 가 하나라도 있으면 login verdict 안 뜸 (board 보임)
    ok = Result(strategy="S1.H1", target="list", url="https://x.org/board",
                status=200, classification=Classification.OK, notable=[], body_path=None)
    d = _diag([ok, _login(["weak login marker + short body"])])
    cases.append(("ok_list_no_login_verdict", "LOGIN" not in d.verdict, d.verdict))

    return cases
