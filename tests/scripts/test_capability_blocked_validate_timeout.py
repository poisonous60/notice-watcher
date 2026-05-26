"""`scripts.register._generation_error_capability_blocked_reason` 의 validator-timeout 게이트.

agentic 의 `validate_built_config` 가 LLM-생성 config 의 `fetch_list` 를 검증 단계에서
호출하는데, 타겟 사이트가 anti-bot 지연·느린 TLS 로 25s 안에 응답 못 하면
`validate_internal_timeout_25s` 를 attempts 에 박는다. 모든 attempt 가 그 패턴이면
LLM 잘못이 아닌 *사이트 능력 부족* — rc=1 gen_fail 대신 rc=5 capability_blocked 로
재분류해 자동 Later 큐로 보낸다 (2026-05-26 games-indie-studios-asia batch 박음).
"""
from __future__ import annotations

import json


def _err(last_feedback):
    class E:
        pass
    e = E()
    e.last_feedback = last_feedback
    return e


def run() -> list[tuple[str, bool, str]]:
    from scripts.register import _generation_error_capability_blocked_reason as classify
    cases: list[tuple[str, bool, str]] = []

    # 1) 모든 attempt 가 validate_internal_timeout → cap_blocked.
    lf = json.dumps([
        {"i": 1, "validate_ok": False, "error": "validate_internal_timeout_25s"},
        {"i": 2, "validate_ok": False, "error": "validate_internal_timeout_25s"},
    ])
    r = classify(_err(lf))
    cases.append(("all_timeout_classified", bool(r and "capability_blocked" in r), str(r or "")[:120]))

    # 2) attempt 1 LLM hallucination + attempt 2 timeout → 혼합, cap_blocked X (LLM 잘못 포함).
    lf = json.dumps([
        {"i": 1, "validate_ok": False, "error": "invalid transform date_time_to_iso"},
        {"i": 2, "validate_ok": False, "error": "validate_internal_timeout_25s"},
    ])
    r = classify(_err(lf))
    cases.append(("mixed_not_classified", r is None, str(r or "")[:120]))

    # 3) 단일 attempt 만 timeout → 보수적, cap_blocked X (>=2 attempt 필요).
    lf = json.dumps([
        {"i": 1, "validate_ok": False, "error": "validate_internal_timeout_25s"},
    ])
    r = classify(_err(lf))
    cases.append(("single_attempt_not_classified", r is None, str(r or "")[:120]))

    # 4) 빈 list / non-list → cap_blocked X (회귀 가드).
    cases.append(("empty_list_not_classified", classify(_err("[]")) is None, ""))
    cases.append(("non_json_not_classified", classify(_err("[FAIL] posts_nonempty: 0건")) is None, ""))

    # 5) HTTP 4xx pattern 은 기존대로 cap_blocked (회귀 가드).
    e = _err("HTTPStatusError: Client error '403 Forbidden' for url 'https://x'")
    r = classify(e)
    cases.append(("http_403_still_classified", bool(r and "HTTP 403" in r), str(r or "")[:120]))

    # 6) validate_internal_timeout_60s (다른 timeout 값) 도 매칭.
    lf = json.dumps([
        {"i": 1, "validate_ok": False, "error": "validate_internal_timeout_60s"},
        {"i": 2, "validate_ok": False, "error": "validate_internal_timeout_60s"},
    ])
    r = classify(_err(lf))
    cases.append(("timeout_60s_classified", bool(r and "capability_blocked" in r), str(r or "")[:120]))

    return cases


if __name__ == "__main__":
    fail = 0
    for name, ok, msg in run():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  ({msg})")
        fail += 0 if ok else 1
    raise SystemExit(0 if fail == 0 else 1)
