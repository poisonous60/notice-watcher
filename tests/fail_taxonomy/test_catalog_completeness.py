"""FAIL_CATALOG 의 모든 *fixed* Subkind 가 test_classify_fail 의 CASES 에 등장하는지 검증.

새 fixed Subkind 추가했는데 fixture 안 더했으면 여기서 차단됨. dynamic Subkind (`recognizer:*`,
`[FAIL]:<check>`) 는 catalog 외 이름이 와도 OK 라서 검증 제외.

추가로:
- catalog 의 fail_kind name 들이 dashboard filter 옵션 + pseudo_kinds 와 충돌 없는지
- 모든 fixed Subkind name 이 catalog 안에서 unique 한지
"""
from __future__ import annotations

import sys


def run() -> list[tuple[str, bool, str]]:
    from bot.fail_taxonomy import FAIL_CATALOG, fail_filter_options, pseudo_kinds
    from tests.fail_taxonomy.test_classify_fail import CASES

    cases: list[tuple[str, bool, str]] = []

    # 1. CASES 의 expect_sub 모음
    case_subs_by_kind: dict[str, set[str]] = {}
    for _name, _args, expect_kind, expect_sub in CASES:
        if expect_sub is None:
            continue
        case_subs_by_kind.setdefault(expect_kind, set()).add(expect_sub)

    # 2. 각 fail_kind 의 fixed Subkind 들이 CASES 에 다 등장하는지
    for fk in FAIL_CATALOG:
        fixed_subs = [sk.name for sk in fk.subkinds if not sk.dynamic]
        if not fixed_subs:
            continue
        case_subs = case_subs_by_kind.get(fk.name, set())
        missing = [s for s in fixed_subs if s not in case_subs]
        ok = not missing
        msg = (f"all {len(fixed_subs)} fixed subkinds covered"
               if ok else f"missing fixtures: {missing}")
        cases.append((f"completeness:{fk.name}", ok, msg))

    # 3. fixed Subkind name 유일성 (catalog 전체)
    all_fixed_names: list[str] = []
    for fk in FAIL_CATALOG:
        for sk in fk.subkinds:
            if not sk.dynamic:
                all_fixed_names.append(sk.name)
    dupes = sorted({n for n in all_fixed_names if all_fixed_names.count(n) > 1})
    cases.append(("subkind_name_unique", not dupes,
                  f"dupes={dupes}" if dupes else f"{len(all_fixed_names)} 개 unique"))

    # 4. dashboard filter dropdown 의 fail_kind 가 catalog 또는 pseudo 안에 존재
    catalog_names = {fk.name for fk in FAIL_CATALOG}
    pseudo_names = set(pseudo_kinds().keys())
    valid = catalog_names | pseudo_names
    opts = fail_filter_options()
    bad = [o for o in opts if o not in valid]
    cases.append(("filter_options_in_catalog", not bad,
                  f"unknown opts: {bad}" if bad else f"{len(opts)} opts OK"))

    # 4b. 역방향 — catalog 의 모든 FailKind 가 dropdown 에 노출되는지 (새 FailKind 추가했는데
    #     filter 에 안 박은 case 차단).
    opts_set = set(opts)
    missing = [fk.name for fk in FAIL_CATALOG if fk.name not in opts_set]
    cases.append(("all_catalog_kinds_in_dropdown", not missing,
                  f"missing in dropdown: {missing}" if missing
                  else f"all {len(FAIL_CATALOG)} FailKinds exposed"))

    # 5. severity 값 유효성 — 'ok'/'warn'/'error'/'' 만 허용
    allowed = {"ok", "warn", "error", ""}
    bad_sev = [(fk.name, fk.severity) for fk in FAIL_CATALOG if fk.severity not in allowed]
    cases.append(("severity_values_allowed", not bad_sev,
                  f"bad: {bad_sev}" if bad_sev else "all severity ∈ {ok,warn,error,''}"))

    return cases


if __name__ == "__main__":
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    results = run()
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {d}")
    sys.exit(0 if all(ok for _, ok, _ in results) else 1)
