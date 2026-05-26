"""probe.diagnose — WAF_406_BLOCK verdict 태깅 (codex P-5 review finding 3, 2026-05-26).

real WAF (KR IDC NHN/Naver/WAPPLES) 가 origin 자체 게이트로 HTTP 406 던지는 케이스 →
verdict 에 WAF_406_BLOCK 박혀야 register 가 curl_cffi 권장 메시지 분기.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


def _diagnose(static_results, baseline_ok=True):
    from probe.diagnose import diagnose
    from probe.types import Result, Classification
    bl = Result(strategy="B1", target="baseline", url="https://x.example/",
                status=200 if baseline_ok else 503,
                classification=Classification.OK if baseline_ok else Classification.BLOCKED_BOT)
    with tempfile.TemporaryDirectory() as td:
        lc = Path(td) / "lc.json"
        lc.write_text(json.dumps({}))
        return diagnose(slug="t", url="https://x.example/",
                        baseline={"B1": bl}, static_results=static_results,
                        headless=None, captured_retry=None, s1l=None,
                        external_results=[], paid_results=[],
                        list_candidates_path=lc, article_result=None, robots_info={})


def _r(status, cls=None):
    from probe.types import Result, Classification
    return Result(strategy="S1.H1", target="list", url="https://x.example/",
                  status=status,
                  classification=cls or Classification.BLOCKED_BOT)


def run() -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []

    # all 406 → WAF_406_BLOCK
    d = _diagnose([_r(406), _r(406)])
    cases.append(("all_406_tags_waf", "WAF_406_BLOCK" in d.verdict, f"verdict={d.verdict!r}"))

    # all 403 → no WAF_406, ENTRY_BLOCKED (baseline OK 분기)
    d2 = _diagnose([_r(403), _r(403)])
    cases.append(("all_403_no_waf", "WAF_406_BLOCK" not in d2.verdict, f"verdict={d2.verdict!r}"))
    cases.append(("all_403_entry_blocked", "ENTRY_BLOCKED" in d2.verdict, f"verdict={d2.verdict!r}"))

    # mixed 406 + 403 → not all 406 → no WAF_406
    d3 = _diagnose([_r(406), _r(403)])
    cases.append(("mixed_406_403_no_waf", "WAF_406_BLOCK" not in d3.verdict, f"verdict={d3.verdict!r}"))

    # 406 + None(unset status, e.g. error) → all(r.status==406) False → no WAF_406
    d4 = _diagnose([_r(406), _r(None)])
    cases.append(("partial_none_status_no_waf", "WAF_406_BLOCK" not in d4.verdict, f"verdict={d4.verdict!r}"))

    # empty static_results → no WAF_406 (guard)
    d5 = _diagnose([])
    cases.append(("empty_static_no_waf", "WAF_406_BLOCK" not in d5.verdict, f"verdict={d5.verdict!r}"))

    # all None status → all() True 위험 → 가드 (status==406 None comparison False)
    d6 = _diagnose([_r(None), _r(None)])
    cases.append(("all_none_status_no_waf", "WAF_406_BLOCK" not in d6.verdict, f"verdict={d6.verdict!r}"))

    return cases
