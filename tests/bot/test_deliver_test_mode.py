"""ADR 0017 + B (codex review applied) — deliver_due 의 NOTIFY_TEST_TARGETS 처리 단위 테스트.

테스트 범위:
  - env 없음 = test_mode_requested=False, allow={}
  - env 'owner' + OWNER_USER_ID 설정 = allow={'dm:<owner>'}
  - env 'owner' + OWNER_USER_ID 미설정 = TestTargetsConfigError (fail closed, codex HIGH)
  - env 'kind:id,kind:id' = 그대로 parse
  - env 'invalidformat' = TestTargetsConfigError (fail closed)
  - env 빈 = test_mode_requested=False
"""
from __future__ import annotations

import os
from pathlib import Path


def run() -> list[tuple[str, bool, str]]:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from scripts.deliver_due import _parse_test_targets, TestTargetsConfigError

    cases: list[tuple[str, bool, str]] = []

    # 1. env 미설정
    os.environ.pop("NOTIFY_TEST_TARGETS", None)
    req, allow = _parse_test_targets()
    cases.append(("env_unset_no_test_mode",
                  req is False and allow == set(), f"req={req} allow={allow}"))

    # 2. env 빈 문자열도 마찬가지
    os.environ["NOTIFY_TEST_TARGETS"] = "  "
    req, allow = _parse_test_targets()
    cases.append(("env_empty_no_test_mode",
                  req is False and allow == set(), f"req={req} allow={allow}"))

    # 3. 명시적 kind:id 들
    os.environ["NOTIFY_TEST_TARGETS"] = "dm:111,channel:222"
    req, allow = _parse_test_targets()
    cases.append(("env_explicit_allow",
                  req is True and allow == {"dm:111", "channel:222"},
                  f"req={req} allow={allow}"))

    # 4. 'owner' + OWNER_USER_ID 설정
    os.environ["NOTIFY_TEST_TARGETS"] = "owner"
    os.environ["OWNER_USER_ID"] = "999888"
    req, allow = _parse_test_targets()
    cases.append(("env_owner_with_id",
                  req is True and allow == {"dm:999888"},
                  f"req={req} allow={allow}"))

    # 5. 'owner' + OWNER_USER_ID 미설정 → fail closed (codex HIGH)
    os.environ["NOTIFY_TEST_TARGETS"] = "owner"
    os.environ["OWNER_USER_ID"] = ""
    # bot.config 의 owner_user_id() 는 load_env() 부르고 env 본다 — load_env 이전에 .env 가 OWNER_USER_ID 설정 가능.
    # 그래서 정말 fail closed 로 가는지 확인하려면 owner_user_id() 함수를 직접 mock 해야 안전.
    import scripts.deliver_due as dd
    orig_owner = dd.owner_user_id
    dd.owner_user_id = lambda: ""
    try:
        raised = False
        try:
            req, allow = _parse_test_targets()
        except TestTargetsConfigError:
            raised = True
        cases.append(("env_owner_no_id_fail_closed", raised,
                      f"raised={raised} (req={req if not raised else 'N/A'} allow={allow if not raised else 'N/A'})"))
    finally:
        dd.owner_user_id = orig_owner

    # 6. 형식 이상만 = fail closed
    os.environ["NOTIFY_TEST_TARGETS"] = "garbage_no_colon"
    raised = False
    try:
        req, allow = _parse_test_targets()
    except TestTargetsConfigError:
        raised = True
    cases.append(("env_bad_format_fail_closed", raised, f"raised={raised}"))

    # 7. 'owner' + valid (정상 회복) — 5 의 잔재가 다음 테스트에 영향 X 확인
    os.environ["NOTIFY_TEST_TARGETS"] = "dm:123"
    req, allow = _parse_test_targets()
    cases.append(("env_recovery_after_fail",
                  req is True and allow == {"dm:123"}, f"req={req} allow={allow}"))

    # 정리
    os.environ.pop("NOTIFY_TEST_TARGETS", None)
    os.environ.pop("OWNER_USER_ID", None)

    return cases


if __name__ == "__main__":
    import sys
    results = run()
    failed = [(n, d) for n, ok, d in results if not ok]
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {d}")
    if failed:
        print(f"\n{len(failed)} FAILED")
        sys.exit(1)
    print(f"\n{len(results)} passed")
