"""deliver_due rev3 — 별도 trailing message 폐기, 한 메시지 안에 inline / digest 푸터 append.

검증:
1. `_status_inline_content` — owed=0 자리 단일 메시지 (broken 또는 empty 또는 mix 1줄)
2. `_broken_footer_for_digest` — digest 마지막 chunk 끝 푸터 (별도 message X)
3. footer max_chars 가드 — broken 슬러그 많아도 cap 보호 (외 N건)
4. 둘 다 비어 None
5. `is_broken` round-trip (race 가드 토대)
6. rev2 의 `_status_notice_content` 함수 제거 확인 (별도 trailing message path 폐기)
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

    tmp = Path(tempfile.mkdtemp(prefix="dd_broken_rev3_"))
    sd = tmp / "poll_state"
    sd.mkdir()
    orig_so = site_ops.STATE_DIR
    orig_rg = _reg.STATE_DIR
    site_ops.STATE_DIR = sd
    _reg.STATE_DIR = sd

    try:
        # 1. inline status — 둘 다 비어 None
        n = dd._status_inline_content(today_kst="2026-05-27", empty_slugs=[], broken_items=[])
        cases.append(("inline_none_when_both_empty", n is None, f"got={n!r}"))

        # 2. inline status — single empty
        n2 = dd._status_inline_content(today_kst="2026-05-27", empty_slugs=["a"], broken_items=[])
        cases.append(("inline_single_empty",
                      n2 and "📭" in n2 and "❗" not in n2 and "\n" not in n2,
                      f"got={n2!r}"))

        # 3. inline status — single broken
        n3 = dd._status_inline_content(today_kst="2026-05-27", empty_slugs=[],
                                          broken_items=[{"slug": "x", "cb": 9}])
        cases.append(("inline_single_broken",
                      n3 and "❗" in n3 and "9회" in n3 and "📭" not in n3,
                      f"got={n3!r}"))

        # 4. inline mixed — 2+ → 헤더 + 슬러그별 줄
        n4 = dd._status_inline_content(today_kst="2026-05-27",
                                          empty_slugs=["a"],
                                          broken_items=[{"slug": "x", "cb": 9},
                                                          {"slug": "y", "cb": 6}])
        ok_mix = (n4 and "📊" in n4 and "❗" in n4 and "📭" in n4
                   and "9회" in n4 and "6회" in n4)
        cases.append(("inline_mixed_header_plus_lines", bool(ok_mix), f"got={n4!r}"))

        # 5. footer — 비어있으면 None
        f0 = dd._broken_footer_for_digest(broken_items=[])
        cases.append(("footer_none_when_empty", f0 is None, f"got={f0!r}"))

        # 6. footer — 정상 케이스 (cap 안)
        f1 = dd._broken_footer_for_digest(broken_items=[{"slug": "foo", "cb": 9},
                                                          {"slug": "bar", "cb": 6}])
        cases.append(("footer_normal",
                      f1 and "참고" in f1 and "foo" in f1 and "bar" in f1
                       and "외" not in f1,
                      f"got={f1!r}"))

        # 7. footer cap — 많은 슬러그 → 외 N건 표시
        many = [{"slug": f"slug_{i}_" + "x"*20, "cb": 10} for i in range(20)]
        f2 = dd._broken_footer_for_digest(broken_items=many, max_chars=200)
        cases.append(("footer_caps_with_overflow",
                      f2 and len(f2) <= 350 and "외" in f2,
                      f"len={len(f2 or '')!r} contains_oe={'외' in (f2 or '')}"))

        # 8. is_broken round-trip
        slug_b = "host_d_root_dddd4444"
        _reg._save_broken(slug_b, "https://d.example/", cb=7, last_status="x")
        broken_before = site_ops.is_broken(slug_b)
        _reg._clear_broken(slug_b)
        broken_after = site_ops.is_broken(slug_b)
        cases.append(("is_broken_toggle",
                      broken_before is True and broken_after is False,
                      f"before={broken_before} after={broken_after}"))

        # 9. rev2 의 별도 trailing message 함수 제거됐는지 — `_status_notice_content` 없어야 함
        cases.append(("rev3_no_status_notice_content",
                      not hasattr(dd, "_status_notice_content"),
                      "rev2 trailing status notice 함수 제거 됐어야 함"))

        # 10. `_empty_notice_content` 는 *보존* — owed>0 + empty_slugs 의 기존 trailing 동작 그대로.
        # rev3 invariant: broken 만 별도 message 금지 (empty 는 그대로). 사용자 정정 (2026-05-27).
        cases.append(("empty_notice_content_preserved",
                      hasattr(dd, "_empty_notice_content"),
                      "broken 만 별도 메시지 금지 — empty trailing 보존"))
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
