"""poll_state/<slug> marker file lifecycle 회귀 테스트.

검증 대상 (codex 2026-05-17 bughunt 발견):
1. `_save_rejected` — 형제 marker (.FAILED, .BUG) + normal state (.json) 일괄 제거
2. `_save_bug` — 형제 .FAILED 제거 + triage_queue prune (REJECTED 는 보존 — marker_kind 우선순위)
3. `migrate_slug_schema.build_mapping` / `rename_state` — .REJECTED/.BUG marker suffix 보존
   (critical: 옛 코드는 stem 에서 `.FAILED` 만 strip → .REJECTED.json 이 normal state 로 변환되는 data corruption)
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path


def _setup_tmp_state(monkeypatch_paths: bool = True) -> Path:
    """임시 STATE_DIR 만들고 register.py / migrate_slug_schema 의 글로벌 경로를 redirect."""
    tmp = Path(tempfile.mkdtemp(prefix="state_lifecycle_"))
    state_dir = tmp / "poll_state"
    state_dir.mkdir()
    return state_dir


def _restore_paths(orig_state: Path, orig_queue: Path):
    from scripts import register as _reg
    _reg.STATE_DIR = orig_state
    _reg.TRIAGE_QUEUE = orig_queue  # type: ignore[attr-defined]


def _test_save_rejected_cleans_siblings() -> tuple[bool, str]:
    """_save_rejected 호출 시 .FAILED + .BUG + <slug>.json 다 제거되고 .REJECTED 만 남아야."""
    from scripts import register as _reg

    state_dir = _setup_tmp_state()
    orig_state = _reg.STATE_DIR
    _reg.STATE_DIR = state_dir
    # learned_blacklist 호출 우회 (외부 자원 없음)
    orig_learn = getattr(_reg, "_learn_pattern", None)
    _reg._learn_pattern = lambda *a, **kw: None  # type: ignore[attr-defined]
    orig_prune = _reg._prune_triage_queue
    _reg._prune_triage_queue = lambda *a, **kw: None  # type: ignore[attr-defined]

    try:
        slug = "test_slug_a"
        # pre-existing 형제들
        (state_dir / f"{slug}.FAILED.json").write_text("{}", encoding="utf-8")
        (state_dir / f"{slug}.BUG.json").write_text("{}", encoding="utf-8")
        (state_dir / f"{slug}.json").write_text("{}", encoding="utf-8")

        _reg._save_rejected(slug, "https://example.com/board", "test reason", learn=False)

        rej_exists = (state_dir / f"{slug}.REJECTED.json").exists()
        failed_gone = not (state_dir / f"{slug}.FAILED.json").exists()
        bug_gone = not (state_dir / f"{slug}.BUG.json").exists()
        state_gone = not (state_dir / f"{slug}.json").exists()

        ok = rej_exists and failed_gone and bug_gone and state_gone
        detail = (f"REJECTED={rej_exists} FAILED_gone={failed_gone} "
                  f"BUG_gone={bug_gone} state_gone={state_gone}")
        return ok, detail
    finally:
        _reg.STATE_DIR = orig_state
        if orig_learn:
            _reg._learn_pattern = orig_learn  # type: ignore[attr-defined]
        _reg._prune_triage_queue = orig_prune  # type: ignore[attr-defined]
        shutil.rmtree(state_dir.parent, ignore_errors=True)


def _test_save_bug_clears_failed_keeps_rejected() -> tuple[bool, str]:
    """_save_bug 호출 시 .FAILED 제거 + queue prune. .REJECTED 는 *보존* (precedence 가 처리)."""
    from scripts import register as _reg

    state_dir = _setup_tmp_state()
    queue = state_dir.parent / "triage_queue.jsonl"
    orig_state = _reg.STATE_DIR
    orig_prune_target = _reg.ROOT  # _prune_triage_queue 가 ROOT 기준 — 트릭으로 우회
    _reg.STATE_DIR = state_dir

    pruned: list[str] = []

    def _fake_prune(slug: str) -> None:
        pruned.append(slug)

    orig_prune = _reg._prune_triage_queue
    _reg._prune_triage_queue = _fake_prune  # type: ignore[attr-defined]

    try:
        slug = "test_slug_b"
        (state_dir / f"{slug}.FAILED.json").write_text("{}", encoding="utf-8")
        (state_dir / f"{slug}.REJECTED.json").write_text('{"reason":"prior"}', encoding="utf-8")

        _reg._save_bug(slug, "https://example.com/x", rc=-1, reason="chromium_lock_timeout", tail="")

        bug_exists = (state_dir / f"{slug}.BUG.json").exists()
        failed_gone = not (state_dir / f"{slug}.FAILED.json").exists()
        rejected_kept = (state_dir / f"{slug}.REJECTED.json").exists()
        queue_pruned = slug in pruned

        ok = bug_exists and failed_gone and rejected_kept and queue_pruned
        detail = (f"BUG={bug_exists} FAILED_gone={failed_gone} "
                  f"REJECTED_kept={rejected_kept} queue_pruned={queue_pruned}")
        return ok, detail
    finally:
        _reg.STATE_DIR = orig_state
        _reg._prune_triage_queue = orig_prune  # type: ignore[attr-defined]
        shutil.rmtree(state_dir.parent, ignore_errors=True)


def _test_migrate_preserves_marker_suffix() -> tuple[bool, str]:
    """migrate_slug_schema 가 .REJECTED.json / .BUG.json marker suffix 보존하는지 (critical fix).

    옛 코드: stem 에서 `.FAILED` 만 strip → `.REJECTED.json` 의 stem 이 `<slug>.REJECTED` 로 남아
    rename_state 가 `.json` suffix 만 match → marker 가 normal state 로 변환되는 data corruption.
    """
    from scripts import migrate_slug_schema as _mig

    tmp = Path(tempfile.mkdtemp(prefix="migrate_marker_"))
    state_dir = tmp / "poll_state"
    state_dir.mkdir()
    configs_dir = tmp / "configs"
    configs_dir.mkdir()

    try:
        # 3 가지 marker + 1 normal state — 다 같은 URL 로 매핑되는 *다른 slug* 쓰지 X
        # (각각 다른 URL = 다른 mapping entry). slug 끝에 host 다르게.
        cases = [
            ("old_a", "https://a.example.com/board", ".FAILED.json"),
            ("old_b", "https://b.example.com/board", ".REJECTED.json"),
            ("old_c", "https://c.example.com/board", ".BUG.json"),
            ("old_d", "https://d.example.com/board", ".json"),
        ]
        for old, url, suffix in cases:
            (state_dir / f"{old}{suffix}").write_text(
                json.dumps({"slug": old, "url": url}), encoding="utf-8")

        # build_mapping — stem 추출 검증 (mapping key 가 slug 자체 — marker suffix 제거됨)
        mapping = _mig.build_mapping(state_dir, configs_dir, conn=None)
        keys = set(mapping.keys())
        expected_keys = {"old_a", "old_b", "old_c", "old_d"}
        keys_ok = keys == expected_keys

        # rename_state — marker suffix 보존 검증
        # new slug 가 도출되도록 url_to_slug 호출 → 그대로 사용. 같은 host 다르므로 collision X.
        renamed_ok_per_case: list[str] = []
        for old, _url, suffix in cases:
            info = mapping[old]
            new = info["new_slug"]
            if old == new:
                renamed_ok_per_case.append(f"{old}=noop")
                continue
            _mig.rename_state(state_dir, configs_dir, old, new)
            # old 파일 사라졌나
            old_gone = not (state_dir / f"{old}{suffix}").exists()
            # new 파일이 *같은 suffix* 로 만들어졌나 (← 핵심)
            new_exists_with_same_suffix = (state_dir / f"{new}{suffix}").exists()
            renamed_ok_per_case.append(
                f"{old}→{new}: suffix={suffix} preserved={new_exists_with_same_suffix} old_gone={old_gone}"
            )
            if not (old_gone and new_exists_with_same_suffix):
                return False, " | ".join(renamed_ok_per_case)

        ok = keys_ok
        detail = f"keys_ok={keys_ok} keys={sorted(keys)} | " + " | ".join(renamed_ok_per_case)
        return ok, detail
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run() -> list[tuple[str, bool, str]]:
    return [
        ("save_rejected_cleans_siblings", *_test_save_rejected_cleans_siblings()),
        ("save_bug_clears_failed_keeps_rejected", *_test_save_bug_clears_failed_keeps_rejected()),
        ("migrate_preserves_marker_suffix", *_test_migrate_preserves_marker_suffix()),
    ]


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    fail = 0
    for name, ok, msg in run():
        mark = "PASS" if ok else "FAIL"
        print(f"  {mark}  {name}  ({msg})")
        if not ok:
            fail += 1
    raise SystemExit(0 if fail == 0 else 1)
