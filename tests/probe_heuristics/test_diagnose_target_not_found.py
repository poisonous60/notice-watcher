"""probe.diagnose TARGET_NOT_FOUND verdict.

regression: 2026-05-17 — d4m0n.tistory.com/10 의 진단이 baseline B1/B2=200·OK 인데
target URL 의 모든 진입 시도 (S1.H2/H3/H4/S4/Hcap) 가 404 NOT_FOUND. verdict_parts
가 모두 비어 "분류 보류" 박혔고 register.py 가 "차단(BLOCKED) 사이트로 보임" 으로
오안내. baseline 살아있는 host 의 target 404 는 BLOCKED 가 아니라 URL 잘못/삭제.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory


covers = ["diagnose_target_not_found_verdict"]


def _mk_result(strategy: str, target: str, classification, status: int = 200, error: str | None = None):
    from probe.types import Result
    return Result(
        strategy=strategy,
        target=target,
        url="https://example.com/10",
        status=status,
        duration_ms=10,
        headers={},
        classification=classification,
        notable=[],
        error=error,
    )


def _run_diagnose(*, baseline_classes, static_classes, headless_class, captured_class):
    from probe.diagnose import diagnose
    from probe.types import Classification

    baseline = {
        "B1": _mk_result("B1", "baseline", baseline_classes[0], status=200),
        "B2": _mk_result("B2", "baseline", baseline_classes[1], status=200),
    }
    static_results = [
        _mk_result(f"S1.H{i+2}", "list", c, status=(404 if c == Classification.NOT_FOUND else 200))
        for i, c in enumerate(static_classes)
    ]
    headless = _mk_result("S4", "list", headless_class,
                          status=(404 if headless_class == Classification.NOT_FOUND else 200)) if headless_class else None
    captured = _mk_result("S1.Hcap", "list", captured_class,
                          status=(404 if captured_class == Classification.NOT_FOUND else 200)) if captured_class else None

    with TemporaryDirectory() as tmp:
        list_cands_path = Path(tmp) / "list_candidates.json"
        list_cands_path.write_text("{}", encoding="utf-8")
        return diagnose(
            slug="test",
            url="https://example.com/10",
            baseline=baseline,
            static_results=static_results,
            headless=headless,
            captured_retry=captured,
            s1l=None,
            external_results=[],
            paid_results=[],
            list_candidates_path=list_cands_path,
            article_result=None,
            robots_info={},
        )


def run() -> list[tuple[str, bool, str]]:
    from probe.types import Classification as C

    cases: list[tuple[str, bool, str]] = []

    # 1. baseline OK + 모든 target NOT_FOUND → TARGET_NOT_FOUND verdict
    d1 = _run_diagnose(
        baseline_classes=[C.OK, C.OK],
        static_classes=[C.NOT_FOUND, C.NOT_FOUND, C.NOT_FOUND],
        headless_class=C.NOT_FOUND,
        captured_class=C.NOT_FOUND,
    )
    cases.append(("baseline_ok_target_all_404", "TARGET_NOT_FOUND" in d1.verdict, d1.verdict))

    # 2. note 에 "URL 의 글이 존재하지 않음" 한국어 안내 박힘
    cases.append(("target_not_found_note_present",
                  any("404" in n and "존재하지 않음" in n for n in d1.notes),
                  str(d1.notes)))

    # 3. baseline OK 인데 target 일부만 NOT_FOUND (한 개라도 OK) → TARGET_NOT_FOUND X
    d3 = _run_diagnose(
        baseline_classes=[C.OK, C.OK],
        static_classes=[C.OK, C.NOT_FOUND, C.NOT_FOUND],
        headless_class=C.NOT_FOUND,
        captured_class=C.NOT_FOUND,
    )
    cases.append(("baseline_ok_target_partial_ok_no_target_not_found",
                  "TARGET_NOT_FOUND" not in d3.verdict, d3.verdict))

    # 4. baseline 이 NOT_FOUND × 다수 = 사이트 자체 404 → BASELINE_BLOCKED 박히고
    #    target 도 NOT_FOUND 면 *추가로* TARGET_NOT_FOUND 박힘 (2026-05-27 url_dead 게이트 확장 —
    #    사이트 통째 404 도 url_dead 로 rc=4 가야 함, 옛 동작은 rc=5 cap_blocked 으로 가는 버그였음).
    d4 = _run_diagnose(
        baseline_classes=[C.NOT_FOUND, C.NOT_FOUND],
        static_classes=[C.NOT_FOUND, C.NOT_FOUND, C.NOT_FOUND],
        headless_class=C.NOT_FOUND,
        captured_class=C.NOT_FOUND,
    )
    cases.append(("baseline_dead_target_not_found_added",
                  "TARGET_NOT_FOUND" in d4.verdict and "BASELINE_BLOCKED" in d4.verdict,
                  d4.verdict))

    # 5. baseline OK + target 다 BLOCKED_BOT → TARGET_NOT_FOUND X (BLOCKED 와 분리)
    d5 = _run_diagnose(
        baseline_classes=[C.OK, C.OK],
        static_classes=[C.BLOCKED_BOT, C.BLOCKED_BOT, C.BLOCKED_BOT],
        headless_class=C.BLOCKED_BOT,
        captured_class=C.BLOCKED_BOT,
    )
    cases.append(("baseline_ok_target_blocked_not_target_not_found",
                  "TARGET_NOT_FOUND" not in d5.verdict, d5.verdict))
    cases.append(("baseline_ok_target_blocked_gets_entry_blocked",
                  "ENTRY_BLOCKED" in d5.verdict, d5.verdict))

    # 6. direct target attempts are all 404, but later captured-header retry trips WAF.
    #    The retry should not hide URL-dead evidence from the primary attempts.
    d6 = _run_diagnose(
        baseline_classes=[C.OK, C.OK],
        static_classes=[C.NOT_FOUND, C.NOT_FOUND, C.NOT_FOUND],
        headless_class=C.NOT_FOUND,
        captured_class=C.BLOCKED_BOT,
    )
    cases.append(("target_404_not_hidden_by_hcap_waf",
                  "TARGET_NOT_FOUND" in d6.verdict, d6.verdict))

    return cases
