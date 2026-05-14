"""scripts/push.py 의 allowlist / 인자 검증 단위 테스트.

SSH/scp 는 호출 안 함 — 인자 파싱과 안전 거부 path 만 검증.
"""
from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts import push  # noqa: E402


def run() -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []

    # ----- 1. 알 수 없는 target → rc=4 -----
    rc = push.push("nonsense")
    cases.append(("unknown_target_rc4", rc == 4, f"rc={rc}"))

    # ----- 2. config target 에 slug 없음 → rc=4 -----
    rc = push.push("config", slug=None)
    cases.append(("missing_slug_rc4", rc == 4, f"rc={rc}"))

    # ----- 3. config target 에 위험 slug → rc=4 -----
    for bad in ("../etc", "slug/with/slash", "slug;rm", "slug with space", "a" * 250):
        rc = push.push("config", slug=bad)
        cases.append((f"bad_slug_rejected[{bad[:20]}]", rc == 4, f"rc={rc}"))

    # ----- 4. routing target 인데 로컬 파일 없음 → rc=3 -----
    # (output/llm_routing.json 은 보통 없음. 있으면 이 테스트 의미 X — skip)
    target_file = push.ROOT / "output" / "llm_routing.json"
    if not target_file.exists():
        rc = push.push("routing")
        cases.append(("missing_local_rc3", rc == 3, f"rc={rc}"))

    # ----- 5. config <safe-slug> 인데 로컬 파일 없음 → rc=3 (slug 검증 통과는 함) -----
    # 안전한 형식이지만 실제 파일 없는 slug 사용
    rc = push.push("config", slug="nonexistent_slug_for_test_x9z")
    cases.append(("safe_slug_missing_file_rc3", rc == 3, f"rc={rc}"))

    # ----- 6. TARGETS dict 자체 — 모든 path 가 DEPLOY_PATH 또는 절대 path -----
    for name, t in push.TARGETS.items():
        cases.append((
            f"target_{name}_well_formed",
            (("{DEPLOY_PATH}" in t.remote_path) or t.remote_path.startswith(("~", "/")))
            and t.local_path != "",
            f"local={t.local_path!r} remote={t.remote_path!r}",
        ))

    return cases


if __name__ == "__main__":
    results = run()
    failed = [(n, d) for n, ok, d in results if not ok]
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {d}")
    if failed:
        print(f"\n{len(failed)} FAILED")
        sys.exit(1)
    print(f"\n{len(results)} passed")
