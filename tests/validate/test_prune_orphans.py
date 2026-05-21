"""scripts.prune_orphans.find_orphans — recognizer slug 변경으로 생긴 orphan 마커 검출.

orphan = 마커(FAILED/REJECTED)의 hash suffix 가 *등록된 config* 의 hash 와 같은데 slug 가 다름
(= 같은 URL 이 다른 slug 로 등록됨). hash = url_to_slug 결정값이라 prefix 만 바뀌어도 보존 → 안전한 키.
"""
from __future__ import annotations

import tempfile
from pathlib import Path


def _touch(d: Path, name: str) -> None:
    (d / name).write_text("{}", encoding="utf-8")


def run() -> list[tuple[str, bool, str]]:
    import scripts.prune_orphans as po
    cases: list[tuple[str, bool, str]] = []

    with tempfile.TemporaryDirectory() as td:
        sd = Path(td)
        # 등록됨 (recognizer slug)
        _touch(sd, "discourse_discuss.python.org_16ebc619.json")
        # orphan: 같은 hash, 다른 slug, FAILED 마커
        _touch(sd, "host_discuss-python-_latest_16ebc619.FAILED.json")
        # 무관 실패 (hash 등록 config 없음) → orphan 아님
        _touch(sd, "host_someother-com_root_deadbeef.FAILED.json")
        # 정상 등록 (마커 없음) → 무시
        _touch(sd, "host_normal-site_board_12345678.json")

        orphans = po.find_orphans(state_dir=sd)
        oslugs = {s for _, s, _ in orphans}

        cases.append(("detects_hash_collision_orphan",
                      "host_discuss-python-_latest_16ebc619" in oslugs,
                      f"orphans={oslugs}"))
        cases.append(("maps_to_registered_slug",
                      any(r == "discourse_discuss.python.org_16ebc619" for _, _, r in orphans),
                      f"{orphans}"))
        cases.append(("ignores_unregistered_failure",
                      "host_someother-com_root_deadbeef" not in oslugs,
                      "deadbeef 는 등록 config 없음 → orphan 아님"))
        cases.append(("count_is_one", len(orphans) == 1, f"got {len(orphans)}"))

    return cases


if __name__ == "__main__":
    fail = 0
    for name, ok, msg in run():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  ({msg})")
        fail += 0 if ok else 1
    raise SystemExit(0 if fail == 0 else 1)
