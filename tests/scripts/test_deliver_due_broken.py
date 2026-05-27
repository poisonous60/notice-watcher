"""deliver_due `_status_notice_content` + BROKEN classification 회귀 테스트.

검증:
1. owed=0 + notify_empty=1 + BROKEN sidecar → status notice 에 broken 항목
2. owed>0 → broken_items 자체에 안 넣음 (호출자 책임 — _flush_target_inner 안에서 분기)
3. 합쳐서 single notice (empty + broken 같이) — chunk message 2개로 안 갈라짐
4. None 반환 — 둘 다 비어있으면
5. notify_empty=0 sub → broken/empty 둘 다 status 진입 X (호출자 책임)
6. recheck 후 BROKEN unlink 되면 broken_items 에서 빠짐 (race 가드 시뮬)
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path


def run() -> list[tuple[str, bool, str]]:
    from bot import site_ops
    from scripts import register as _reg
    import scripts.deliver_due as dd
    cases: list[tuple[str, bool, str]] = []

    tmp = Path(tempfile.mkdtemp(prefix="dd_broken_"))
    sd = tmp / "poll_state"
    sd.mkdir()
    orig_so = site_ops.STATE_DIR
    orig_rg = _reg.STATE_DIR
    site_ops.STATE_DIR = sd
    _reg.STATE_DIR = sd

    try:
        # 1. 둘 다 비어 None
        n = dd._status_notice_content(today_kst="2026-05-27", empty_slugs=[], broken_items=[])
        cases.append(("none_when_both_empty", n is None, f"got={n!r}"))

        # 2. empty 단독 — broken 부분 없음
        n2 = dd._status_notice_content(today_kst="2026-05-27", empty_slugs=["a"], broken_items=[])
        cases.append(("empty_only_no_broken_part",
                      n2 and "❗" not in n2 and "📭" in n2,
                      f"got={n2!r}"))

        # 3. broken 단독 — empty 부분 없음
        n3 = dd._status_notice_content(today_kst="2026-05-27", empty_slugs=[],
                                          broken_items=[{"slug": "x", "cb": 9}])
        cases.append(("broken_only_no_empty_part",
                      n3 and "❗" in n3 and "📭" not in n3,
                      f"got={n3!r}"))

        # 4. 둘 다 — single message (개행으로 합침, message 2개 X)
        n4 = dd._status_notice_content(today_kst="2026-05-27",
                                          empty_slugs=["a", "b"],
                                          broken_items=[{"slug": "x", "cb": 9},
                                                          {"slug": "y", "cb": 6}])
        ok_combined = (n4 and "❗" in n4 and "📭" in n4
                        and n4.count("\n") >= 1)
        cases.append(("combined_single_message",
                      bool(ok_combined), f"got={n4!r}"))

        # 5. broken_items multi 형식 — 사용자 향 안내 cb 회수 노출
        cases.append(("broken_multi_shows_cb",
                      n4 and "9회" in n4 and "6회" in n4,
                      f"got={n4!r}"))

        # 6. is_broken 통합 — sidecar 박으면 True, unlink 하면 False (race 가드 토대)
        slug_b = "host_d_root_dddd4444"
        _reg._save_broken(slug_b, "https://d.example/", cb=7, last_status="x")
        broken_before = site_ops.is_broken(slug_b)
        info = site_ops.broken_info(slug_b) or {}
        _reg._clear_broken(slug_b)
        broken_after = site_ops.is_broken(slug_b)
        cases.append(("is_broken_toggle",
                      broken_before is True and broken_after is False,
                      f"before={broken_before} after={broken_after} info_cb={info.get('consecutive_breakage')}"))
    finally:
        site_ops.STATE_DIR = orig_so
        _reg.STATE_DIR = orig_rg
        shutil.rmtree(tmp, ignore_errors=True)

    return cases


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    results = run()
    failed = [(n, d) for n, ok, d in results if not ok]
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {d}")
    if failed:
        print(f"\n{len(failed)} FAILED")
        sys.exit(1)
    print(f"\n{len(results)} passed")
