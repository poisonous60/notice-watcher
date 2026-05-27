"""`_clear_broken_after_reprobe` — reprobe rc=0 시 cb=0 reset + BROKEN sidecar unlink.

zombie loop 봉합 회귀 — reprobe success path 에 이 호출 빠지면 cb 누적 무한 반복.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path


def run() -> list[tuple[str, bool, str]]:
    from bot import site_ops
    cases: list[tuple[str, bool, str]] = []

    orig = site_ops.STATE_DIR
    tmp = Path(tempfile.mkdtemp(prefix="zombie_reset_"))
    sd = tmp / "poll_state"
    sd.mkdir()
    site_ops.STATE_DIR = sd
    try:
        slug = "host_zombie_root_deadbeef"
        # pre-state: state.json (cb=9, reprobe_enqueued) + BROKEN sidecar
        (sd / f"{slug}.json").write_text(json.dumps({
            "slug": slug, "url": "https://zombie.example/",
            "consecutive_breakage": 9, "last_status": "reprobe_enqueued",
        }), encoding="utf-8")
        (sd / f"{slug}.BROKEN.json").write_text(json.dumps({
            "slug": slug, "consecutive_breakage": 9, "count": 2,
        }), encoding="utf-8")

        # 호출
        site_ops._clear_broken_after_reprobe(slug)

        # state.json cb reset 확인
        d = json.loads((sd / f"{slug}.json").read_text(encoding="utf-8"))
        cases.append(("cb_reset_to_zero",
                      int(d.get("consecutive_breakage", -1)) == 0,
                      f"cb={d.get('consecutive_breakage')}"))
        cases.append(("last_status_marked_recovered",
                      d.get("last_status") == "reprobe_recovered",
                      f"last_status={d.get('last_status')!r}"))

        # BROKEN sidecar unlink
        broken_gone = not (sd / f"{slug}.BROKEN.json").exists()
        cases.append(("broken_sidecar_unlinked", broken_gone, ""))

        # idempotent — state 없거나 BROKEN 없어도 raise X
        slug2 = "host_nostate_root_aaaa1111"
        try:
            site_ops._clear_broken_after_reprobe(slug2)
            ok_idem = True
        except Exception as e:  # noqa: BLE001
            ok_idem = False
        cases.append(("idempotent_no_state", ok_idem, ""))

        # state 만 있고 BROKEN 없을 때 cb reset 만 일어남
        slug3 = "host_state_only_root_bbbb2222"
        (sd / f"{slug3}.json").write_text(json.dumps({
            "slug": slug3, "url": "https://s.example/",
            "consecutive_breakage": 5, "last_status": "x",
        }), encoding="utf-8")
        site_ops._clear_broken_after_reprobe(slug3)
        d3 = json.loads((sd / f"{slug3}.json").read_text(encoding="utf-8"))
        cases.append(("state_only_cb_reset",
                      int(d3.get("consecutive_breakage", -1)) == 0,
                      f"cb={d3.get('consecutive_breakage')}"))
    finally:
        site_ops.STATE_DIR = orig
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
