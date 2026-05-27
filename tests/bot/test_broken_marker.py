"""`.BROKEN.json` health sidecar 라이프사이클 회귀 테스트.

검증:
1. `_save_broken` / `_clear_broken` / `_list_broken` round-trip.
2. `marker_kind` 는 BROKEN 안 봄 (3 종 그대로).
3. `is_blocked(slug)` 는 BROKEN 단독에서 False (blocking 아님).
4. `is_registered(slug)` 는 BROKEN 단독 + state.json 있으면 True.
5. `is_broken(slug)` / `broken_info(slug)` / `broken_slugs()` round-trip.
6. `_save_state` (register success) 가 BROKEN sidecar 도 unlink.
7. `_save_rejected` / `_save_bug` 가 BROKEN sidecar 도 unlink.
8. state-scanner suffix exclusion 일관 — `find_registered_alias` 가 `.BROKEN.json` slug 안 잡음.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path


def _setup_tmp() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="broken_marker_"))
    sd = tmp / "poll_state"
    sd.mkdir()
    return sd


def _patch_state_dir(state_dir: Path):
    from bot import site_ops
    from scripts import register as _reg
    site_ops.STATE_DIR = state_dir
    _reg.STATE_DIR = state_dir


def run() -> list[tuple[str, bool, str]]:
    from bot import site_ops
    from scripts import register as _reg
    cases: list[tuple[str, bool, str]] = []

    orig_state_so = site_ops.STATE_DIR
    orig_state_rg = _reg.STATE_DIR
    orig_learn = _reg._learn_pattern
    orig_prune = _reg._prune_triage_queue
    _reg._learn_pattern = lambda *a, **kw: None
    _reg._prune_triage_queue = lambda *a, **kw: None

    sd = _setup_tmp()
    _patch_state_dir(sd)

    try:
        slug = "host_example-com_root_deadbeef"
        url = "https://example.com/"

        # 1. round-trip
        p = _reg._save_broken(slug, url, cb=5, last_status="poll_timeout",
                                last_note="note text")
        ok_save = p.exists() and p.name == f"{slug}.BROKEN.json"
        info = site_ops.broken_info(slug) or {}
        ok_info = (info.get("slug") == slug and info.get("consecutive_breakage") == 5
                    and info.get("count") == 1 and info.get("last_status") == "poll_timeout")
        cases.append(("save_broken_round_trip", bool(ok_save and ok_info),
                      f"save={ok_save} info={info!r}"))

        # 2. count 누적 — 같은 slug 에 다시 save 하면 count++ + first_at 보존
        p2 = _reg._save_broken(slug, url, cb=7, last_status="reprobe_enqueued")
        info2 = site_ops.broken_info(slug) or {}
        ok_count = (info2.get("count") == 2 and info2.get("first_at") == info.get("first_at")
                     and info2.get("consecutive_breakage") == 7)
        cases.append(("save_broken_increments_count", bool(ok_count), f"info2={info2!r}"))

        # 3. marker_kind 는 BROKEN 안 본다 (FAILED/REJECTED/BUG 만)
        mk = site_ops.marker_kind(slug)
        cases.append(("marker_kind_ignores_broken", mk is None, f"marker_kind={mk!r}"))

        # 4. is_blocked 는 BROKEN 무관 False
        blk = site_ops.is_blocked(slug)
        cases.append(("is_blocked_false_on_broken_only", blk is False, f"is_blocked={blk}"))

        # 5. state.json 도 있으면 is_registered=True (BROKEN sidecar 무관)
        (sd / f"{slug}.json").write_text(json.dumps({"slug": slug, "url": url}), encoding="utf-8")
        reg = site_ops.is_registered(slug)
        cases.append(("is_registered_true_with_broken_only", reg is True, f"is_registered={reg}"))

        # 6. is_broken / broken_info
        cases.append(("is_broken_true", site_ops.is_broken(slug) is True, ""))
        bs = site_ops.broken_slugs()
        cases.append(("broken_slugs_contains_slug", slug in bs, f"broken_slugs={bs}"))

        # 7. _clear_broken
        ok_clr = _reg._clear_broken(slug)
        ok_clr2 = _reg._clear_broken(slug)  # idempotent
        cases.append(("clear_broken_first_True_second_False",
                      ok_clr is True and ok_clr2 is False, f"first={ok_clr} second={ok_clr2}"))
        cases.append(("is_broken_false_after_clear",
                      site_ops.is_broken(slug) is False, ""))

        # 8. _save_state 가 BROKEN 도 unlink (sibling cleanup loop)
        _reg._save_broken(slug, url, cb=3, last_status="x")
        (sd / f"{slug}.FAILED.json").write_text("{}", encoding="utf-8")
        cfg = sd.parent / "configs" / f"{slug}.json"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps({"strategy": "rss"}), encoding="utf-8")
        # _unlearn_pattern_if_match / _append_register_signal_log 도 외부 자원 — 안전하게 우회.
        orig_unlearn = getattr(_reg, "_unlearn_pattern_if_match", None)
        orig_signal = getattr(_reg, "_append_register_signal_log", None)
        _reg._unlearn_pattern_if_match = lambda *a, **kw: 0  # type: ignore[attr-defined]
        _reg._append_register_signal_log = lambda *a, **kw: None  # type: ignore[attr-defined]
        try:
            _reg._save_state(slug, url, cfg, post_ids=[])
            broken_gone = not (sd / f"{slug}.BROKEN.json").exists()
            failed_gone = not (sd / f"{slug}.FAILED.json").exists()
            cases.append(("save_state_clears_BROKEN_and_FAILED",
                          broken_gone and failed_gone,
                          f"broken_gone={broken_gone} failed_gone={failed_gone}"))
        finally:
            if orig_unlearn:
                _reg._unlearn_pattern_if_match = orig_unlearn  # type: ignore[attr-defined]
            if orig_signal:
                _reg._append_register_signal_log = orig_signal  # type: ignore[attr-defined]

        # 9. _save_bug 가 BROKEN 도 unlink
        slug_b = "host_bug-test_root_aaaa1111"
        _reg._save_broken(slug_b, url, cb=4, last_status="x")
        _reg._save_bug(slug_b, url, rc=-2, reason="subprocess timeout")
        broken_after_bug = (sd / f"{slug_b}.BROKEN.json").exists()
        bug_exists = (sd / f"{slug_b}.BUG.json").exists()
        cases.append(("save_bug_clears_BROKEN",
                      bug_exists and not broken_after_bug,
                      f"bug_exists={bug_exists} broken_remains={broken_after_bug}"))

        # 10. _save_rejected 가 BROKEN 도 unlink
        slug_r = "host_rej-test_root_bbbb2222"
        _reg._save_broken(slug_r, url, cb=4, last_status="x")
        _reg._save_rejected(slug_r, url, reason="permanent reject", learn=False)
        broken_after_rej = (sd / f"{slug_r}.BROKEN.json").exists()
        rej_exists = (sd / f"{slug_r}.REJECTED.json").exists()
        cases.append(("save_rejected_clears_BROKEN",
                      rej_exists and not broken_after_rej,
                      f"rej_exists={rej_exists} broken_remains={broken_after_rej}"))

        # 11. find_registered_alias 가 BROKEN-only suffix 파일을 normal state 로 안 봄
        # (마커 단독 + base state 없는 경우 — alias 후보 절대 X)
        slug_orphan = "host_orphan_root_cccc3333"
        _reg._save_broken(slug_orphan, "https://orphan.example.com/", cb=4, last_status="x")
        alias = site_ops.find_registered_alias("https://orphan.example.com/",
                                                exclude_slug="other_xxxxxxxx")
        cases.append(("alias_skips_broken_only_marker", alias is None, f"alias={alias!r}"))

        # 12. _save_broken slug regex 검증
        try:
            _reg._save_broken("bad slug with spaces", url, cb=1, last_status="x")
            slug_validated = False
        except ValueError:
            slug_validated = True
        cases.append(("save_broken_validates_slug", slug_validated, ""))

    finally:
        site_ops.STATE_DIR = orig_state_so
        _reg.STATE_DIR = orig_state_rg
        _reg._learn_pattern = orig_learn
        _reg._prune_triage_queue = orig_prune
        shutil.rmtree(sd.parent, ignore_errors=True)

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
