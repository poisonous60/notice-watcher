"""majority NOT_FOUND + 잔여 empty-shell BLOCKED_BOT → TARGET_NOT_FOUND.

lethalcompany.com / contentwarning.com 케이스: 4개 strategy 중 3개 JS-redirect-to-parked
NOT_FOUND, 1개 (S1.H4) `suspiciously empty body 154 bytes` BLOCKED_BOT. all() 깨져서
TARGET_NOT_FOUND 안 박히고 cap_blocked 으로 새던 버그.
"""
from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


covers = ["diagnose_majority_not_found_with_empty_shell"]


def _mk(strategy: str, classification, *, status: int = 200, notable=None):
    from probe.types import Result

    return Result(
        strategy=strategy,
        target="list",
        url="https://lethalcompany.com/",
        status=status,
        duration_ms=10,
        headers={},
        classification=classification,
        notable=notable or [],
        error=None,
    )


def _diagnose(static_results, headless=None):
    from probe.diagnose import diagnose
    from probe.types import Classification

    baseline = {
        "B1": _mk("B1", Classification.OK, status=200),
        "B2": _mk("B2", Classification.OK, status=200),
    }
    with TemporaryDirectory() as tmp:
        list_candidates_path = Path(tmp) / "list_candidates.json"
        list_candidates_path.write_text("{}", encoding="utf-8")
        return diagnose(
            slug="test",
            url="https://lethalcompany.com/",
            baseline=baseline,
            static_results=static_results,
            headless=headless,
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

    # 3 NF + 1 empty-shell BLOCKED_BOT → TARGET_NOT_FOUND
    statics = [
        _mk("S1.H2", Classification.NOT_FOUND, notable=["JS-redirect to parked path"]),
        _mk("S1.H3", Classification.NOT_FOUND, notable=["JS-redirect to parked path"]),
        _mk("S1.H4", Classification.BLOCKED_BOT,
            notable=["suspiciously empty body (154 bytes) — UA/header filter suspected"]),
        _mk("S1.Hcap", Classification.NOT_FOUND, notable=["JS-redirect to parked path"]),
    ]
    d1 = _diagnose(statics)
    cases.append(
        (
            "majority_not_found_with_empty_shell_blocked_bot_gives_target_not_found",
            "TARGET_NOT_FOUND" in d1.verdict,
            d1.verdict,
        )
    )

    # OK 응답이 1개라도 있으면 board 가능 — TARGET_NOT_FOUND 안 박혀야
    statics2 = [
        _mk("S1.H2", Classification.NOT_FOUND, notable=["JS-redirect to parked path"]),
        _mk("S1.H3", Classification.OK, status=200),
        _mk("S1.H4", Classification.BLOCKED_BOT,
            notable=["suspiciously empty body (154 bytes)"]),
    ]
    d2 = _diagnose(statics2)
    cases.append(
        (
            "ok_response_blocks_target_not_found",
            "TARGET_NOT_FOUND" not in d2.verdict,
            d2.verdict,
        )
    )

    # 잔여 BLOCKED_BOT 이 cloudflare/anti-bot (empty-shell 아님) 이면 majority 룰 미적용
    statics3 = [
        _mk("S1.H2", Classification.NOT_FOUND, notable=["JS-redirect to parked path"]),
        _mk("S1.H3", Classification.NOT_FOUND, notable=["JS-redirect to parked path"]),
        _mk("S1.H4", Classification.BLOCKED_BOT,
            notable=["strong bot marker: Just a moment"]),
    ]
    d3 = _diagnose(statics3)
    cases.append(
        (
            "blocked_bot_with_cloudflare_signal_not_treated_as_empty_shell",
            "TARGET_NOT_FOUND" not in d3.verdict,
            d3.verdict,
        )
    )

    return cases


if __name__ == "__main__":
    failed = [(n, m) for n, ok, m in run() if not ok]
    if failed:
        raise SystemExit(failed)
