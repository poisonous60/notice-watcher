"""docs/fail 분류.md 가 bot/fail_taxonomy.py 의 FAIL_CATALOG 와 동기됐는지 검증.

`scripts/gen_fail_taxonomy_doc.py --check` 를 subprocess 로 호출 — drift 시 fail.

새 Subkind 추가 후 doc 재생성 잊었으면 여기서 차단됨. pre-push hook 이 자동 실행.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def run() -> list[tuple[str, bool, str]]:
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts" / "gen_fail_taxonomy_doc.py"
    cases: list[tuple[str, bool, str]] = []

    try:
        result = subprocess.run(
            [sys.executable, str(script), "--check"],
            capture_output=True, text=True, cwd=str(root), timeout=30, encoding="utf-8",
        )
    except Exception as e:
        cases.append(("doc_drift_subprocess", False, f"{type(e).__name__}: {e}"))
        return cases

    ok = result.returncode == 0
    if ok:
        msg = (result.stdout.strip() or "(empty stdout)")
    else:
        # diff 가 stderr 에 박혀 들어옴 — 너무 길면 잘라줌.
        err = (result.stderr or "").strip()
        if len(err) > 600:
            err = err[:600] + "... <truncated>"
        msg = f"rc={result.returncode}; stderr={err}"
    cases.append(("docs/fail 분류.md drift vs FAIL_CATALOG", ok, msg))
    return cases


if __name__ == "__main__":
    results = run()
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {d}")
    sys.exit(0 if all(ok for _, ok, _ in results) else 1)
