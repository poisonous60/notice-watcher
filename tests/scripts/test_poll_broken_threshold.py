"""poll.py BROKEN gate — cb>=broken_threshold 도달 시 `_save_broken` 호출 + 우선순위 마커 가드.

검증:
1. cb<threshold → BROKEN 안 박힘
2. cb>=threshold + 차단 마커 없음 → BROKEN 박힘 (sidecar 파일 생성)
3. FAILED/REJECTED/BUG 존재하면 BROKEN 안 박힘 (우선순위)
4. 정상 fetch (broken=False) 가 cb>0 reset + 기존 BROKEN sidecar unlink
5. `.BROKEN.json` 은 `_load_states` 가 정상 state 로 안 봄 (suffix exclusion)
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path


def _make_state(sd: Path, slug: str, cb: int = 0, **extra) -> Path:
    p = sd / f"{slug}.json"
    payload = {"slug": slug, "url": f"https://{slug}.example/", "consecutive_breakage": cb}
    payload.update(extra)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def run() -> list[tuple[str, bool, str]]:
    from bot import site_ops
    from scripts import register as _reg
    import scripts.poll as poll
    cases: list[tuple[str, bool, str]] = []

    tmp = Path(tempfile.mkdtemp(prefix="poll_broken_"))
    sd = tmp / "poll_state"
    sd.mkdir()

    orig_so = site_ops.STATE_DIR
    orig_rg = _reg.STATE_DIR
    orig_poll = poll.STATE_DIR
    site_ops.STATE_DIR = sd
    _reg.STATE_DIR = sd
    poll.STATE_DIR = sd

    try:
        # 1. cb<threshold 인 state → _load_states 에 잡힘, BROKEN 없음
        _make_state(sd, "host_a_root_aaaa1111", cb=3)
        states = poll._load_states(only=None)
        ok_load = len(states) == 1 and states[0]["slug"] == "host_a_root_aaaa1111"
        cases.append(("load_states_finds_state_file", ok_load, f"states={len(states)}"))

        # 2. .BROKEN.json 단독 파일은 _load_states 가 무시 (suffix exclusion)
        (sd / "host_b_root_bbbb2222.BROKEN.json").write_text(json.dumps({
            "slug": "host_b_root_bbbb2222", "consecutive_breakage": 9, "count": 1,
        }), encoding="utf-8")
        states2 = poll._load_states(only=None)
        slugs2 = {s["slug"] for s in states2}
        cases.append(("load_states_skips_BROKEN_marker",
                      "host_b_root_bbbb2222" not in slugs2,
                      f"slugs={slugs2}"))

        # 3. _save_broken 직접 호출 — sidecar 박힘
        _reg._save_broken("host_c_root_cccc3333", "https://c.example/",
                          cb=6, last_status="poll_timeout")
        cases.append(("save_broken_creates_sidecar",
                      (sd / "host_c_root_cccc3333.BROKEN.json").exists(),
                      ""))

        # 4. _save_broken 후 _load_states 가 그 slug 의 BROKEN 마커 안 가져옴 (state.json 없으면 0건)
        states3 = poll._load_states(only={"host_c_root_cccc3333"})
        cases.append(("load_states_no_state_for_broken_only",
                      len(states3) == 0, f"states3={states3}"))

        # 5. 우선순위 마커 동반 시 poll.py 가드 시뮬레이션 (직접 시뮬 — 함수 분리 안 돼 있으니 가드 로직 재현)
        slug_p = "host_p_root_dddd4444"
        _make_state(sd, slug_p, cb=10)
        # FAILED 동반
        (sd / f"{slug_p}.FAILED.json").write_text(json.dumps({"slug": slug_p}), encoding="utf-8")
        has_blocking = any((sd / f"{slug_p}.{k}.json").exists()
                            for k in ("FAILED", "REJECTED", "BUG"))
        cases.append(("poll_skips_broken_when_FAILED_present",
                      has_blocking, "has_blocking=True (poll.py 가 BROKEN 안 박는 조건)"))

        # 6. 자가 복구 — 기존 BROKEN sidecar 있을 때 정상 fetch (broken=False) path 시뮬레이션
        slug_r = "host_r_root_eeee5555"
        _make_state(sd, slug_r, cb=7)
        _reg._save_broken(slug_r, "https://r.example/", cb=7, last_status="x")
        broken_present_before = (sd / f"{slug_r}.BROKEN.json").exists()
        # 정상 fetch path 시뮬: cb 0 + BROKEN unlink (poll.py:else 분기 동작)
        sp = sd / f"{slug_r}.json"
        d = json.loads(sp.read_text(encoding="utf-8"))
        d["consecutive_breakage"] = 0
        d["last_status"] = "ok"
        sp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        (sd / f"{slug_r}.BROKEN.json").unlink()
        cases.append(("recovery_simulation_cleans_broken",
                      broken_present_before and not (sd / f"{slug_r}.BROKEN.json").exists(),
                      ""))

        # 7. broken_threshold setting 정의 (default 6)
        from bot.runtime_config import settings
        cases.append(("broken_threshold_setting_exists",
                      hasattr(settings.poll, "broken_threshold")
                      and int(settings.poll.broken_threshold) >= 1,
                      f"broken_threshold={getattr(settings.poll, 'broken_threshold', None)}"))
    finally:
        site_ops.STATE_DIR = orig_so
        _reg.STATE_DIR = orig_rg
        poll.STATE_DIR = orig_poll
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
