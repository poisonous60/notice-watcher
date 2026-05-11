"""triage.py — 봇(N100)에서 자동 등록이 실패한 사이트들을 dev박스로 가져와 일괄 처리.

자동 등록 실패의 흔적 두 가지 (둘 다 N100 의 `~/notice-watcher/output/`):
  - `output/poll_state/<slug>.FAILED.json` : register.py 가 씀 — `reason` / `last_feedback`(=`[FAIL] <체크>` …) / `last_config`(자동 생성된 마지막 시도).
  - `output/triage_queue.jsonl`            : 봇이 `_ensure_registered` 실패 때마다 한 줄씩 append — `{ts,url,slug,via("preview"|"watch"),requested_by,register_tail}`.
성공 등록되면(자동이든 `register.py --config` 든) `_save_state` 가 둘 다 정리한다.

흐름:  python scripts/triage.py pull          # N100 → 로컬 (FAILED.json + triage_queue.jsonl + 각 실패 slug 의 probe/)
       python scripts/triage.py list          # 로컬에 받아온 실패 목록 표
       python scripts/triage.py show <slug>   # 그 slug 의 .FAILED.json(사유·last_config) + probe 산출물 위치 + 요청자
   → 그다음 hand-config 스킬 "모드 B(triage)" 로 사이트별 처리(probe 고치거나 손 config/손어댑터 작성 → register --config → N100 배포).

N100 호스트: 환경변수 `DEPLOY_HOST`(기본 `aaaa@<lan-ip>`) / `DEPLOY_PATH`(기본 `~/notice-watcher`).
  IP 가 DHCP 라 바뀌었으면 `DEPLOY_HOST=aaaa@<새IP>` 로. N100 콘솔에서 `ip a` 로 확인 — `docs/운영 메모.md` §1~2.
  ※ ssh/scp 가 PATH 에 있어야 함(Windows 10+ 기본 포함).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
STATE_DIR = OUTPUT / "poll_state"
QUEUE = OUTPUT / "triage_queue.jsonl"
PROBE_DIR = OUTPUT / "probe"

DEPLOY_HOST = os.environ.get("DEPLOY_HOST", "aaaa@<lan-ip>")
DEPLOY_PATH = os.environ.get("DEPLOY_PATH", "~/notice-watcher")

_FAILED_SUFFIX = ".FAILED.json"


def _run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()


def _failed_slugs() -> list[str]:
    if not STATE_DIR.exists():
        return []
    return sorted(p.name[: -len(_FAILED_SUFFIX)] for p in STATE_DIR.glob(f"*{_FAILED_SUFFIX}"))


def _read_queue() -> list[dict]:
    if not QUEUE.exists():
        return []
    out: list[dict] = []
    for line in QUEUE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def _load_failed(slug: str) -> dict:
    fp = STATE_DIR / f"{slug}{_FAILED_SUFFIX}"
    if not fp.exists():
        return {}
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _first_fail_line(last_feedback: str) -> str:
    lines = [l.strip() for l in (last_feedback or "").splitlines() if l.strip()]
    return next((l for l in lines if "[FAIL]" in l), lines[0] if lines else "")


# --------------------------------------------------------------------------- #
def cmd_pull() -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)

    # 1) <slug>.FAILED.json 들 — 원격 셸이 glob 확장. 매치 0개면 scp 가 비0 으로 끝남(에러 아님).
    rc, out = _run(["scp", "-q", f"{DEPLOY_HOST}:{DEPLOY_PATH}/output/poll_state/*{_FAILED_SUFFIX}", f"{STATE_DIR}{os.sep}"])
    if rc != 0 and not any(s in out for s in ("No such file", "not a regular file", "matches no files")):
        sys.stderr.write(f"[triage pull] FAILED.json 가져오기 경고: {out}\n")

    # 2) triage_queue.jsonl (없을 수 있음)
    _run(["scp", "-q", f"{DEPLOY_HOST}:{DEPLOY_PATH}/output/triage_queue.jsonl", str(QUEUE)])

    # 3) 각 실패 slug 의 probe 산출물 디렉토리 (진단 재료)
    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    slugs = _failed_slugs()
    for slug in slugs:
        _run(["scp", "-rq", f"{DEPLOY_HOST}:{DEPLOY_PATH}/output/probe/{slug}", f"{PROBE_DIR}{os.sep}"])

    nq = len({e.get("slug") for e in _read_queue()})
    print(f"[triage pull] {DEPLOY_HOST}:{DEPLOY_PATH}/output → {OUTPUT}")
    print(f"  FAILED.json: {len(slugs)}건   triage_queue slug: {nq}건   probe 디렉토리: {sum(1 for s in slugs if (PROBE_DIR / s).exists())}개")
    print("  → `python scripts/triage.py list`")
    return 0


def cmd_list() -> int:
    slugs = set(_failed_slugs())
    q = _read_queue()
    q_by_slug: dict[str, list[dict]] = {}
    for e in q:
        q_by_slug.setdefault(str(e.get("slug") or ""), []).append(e)
    all_slugs = sorted(slugs | set(k for k in q_by_slug if k))
    if not all_slugs:
        print("처리할 실패 등록 없음. (먼저 `python scripts/triage.py pull` — N100 에서 가져오기)")
        return 0
    rows = []
    for slug in all_slugs:
        d = _load_failed(slug)
        qs = q_by_slug.get(slug, [])
        url = d.get("url") or (qs[-1].get("url", "") if qs else "")
        when = (d.get("failed_at") or (qs[-1].get("ts", "") if qs else "") or "")[:19]
        fail1 = _first_fail_line(d.get("last_feedback", "")) or (qs[-1].get("register_tail", "").splitlines() or [""])[-1].strip()
        via = ",".join(sorted({str(r.get("via", "?")) for r in qs})) or "-"
        who = ",".join(sorted({str((r.get("requested_by") or {}).get("name") or "?") for r in qs})) or "-"
        has_local_failed = "y" if slug in slugs else "-"
        rows.append((slug, when, via, who, has_local_failed, fail1[:58], url))
    w_slug = max(len("slug"), max(len(r[0]) for r in rows))
    w_who = max(len("by"), max(len(r[3]) for r in rows))
    print(f"{'slug':<{w_slug}}  {'failed_at':<19}  {'via':<10}  {'by':<{w_who}}  F  {'[FAIL] / 마지막줄':<58}  url")
    for r in rows:
        print(f"{r[0]:<{w_slug}}  {r[1]:<19}  {r[2]:<10}  {r[3]:<{w_who}}  {r[4]}  {r[5]:<58}  {r[6]}")
    print(f"\n  F=y → 로컬에 <slug>.FAILED.json 있음(상세 진단 가능). F=- → triage_queue 에만 있음(`pull` 다시 하거나 직접 probe).")
    print(f"  자세히: python scripts/triage.py show <slug>")
    print(f"  처리:   hand-config 스킬 모드 B  (사이트별로: 진단 → probe 수정 or 손 config/손어댑터 → register --config → N100 배포)")
    return 0


def cmd_show(slug: str) -> int:
    d = _load_failed(slug)
    if d:
        print(f"=== {STATE_DIR / (slug + _FAILED_SUFFIX)} ===")
        print(f"url         : {d.get('url')}")
        print(f"failed_at   : {d.get('failed_at')}")
        print(f"reason      : {d.get('reason')}")
        print(f"last_feedback:\n{d.get('last_feedback')}")
        lc = d.get("last_config")
        if lc is not None:
            print(f"\nlast_config (자동 생성된 마지막 시도 — 여기서 selector/path 한두 개만 고치면 될 때도 많음):")
            print(json.dumps(lc, ensure_ascii=False, indent=2))
    else:
        print(f"(로컬에 {slug}{_FAILED_SUFFIX} 없음 — `python scripts/triage.py pull` 했는지 확인. triage_queue 에만 있을 수도.)")

    qs = [e for e in _read_queue() if str(e.get("slug")) == slug]
    if qs:
        print(f"\n=== triage_queue.jsonl — {len(qs)}건 (누가/언제/어떤 명령) ===")
        for e in qs:
            print(f"  {e.get('ts','')}  via={e.get('via')}  by={(e.get('requested_by') or {}).get('name')}  {e.get('url')}")
        tail = (qs[-1].get("register_tail") or "").strip()
        if tail:
            print(f"  마지막 register 출력 꼬리:\n    " + "\n    ".join(tail.splitlines()[-8:]))

    pd = PROBE_DIR / slug
    if pd.exists():
        print(f"\n=== probe 산출물: {pd} ===")
        for f in sorted(pd.iterdir()):
            print(f"  {f.name}")
        print(f"  → summary.txt / list_candidates.json / article_candidates.json / traffic.har / diagnosis.json 부터 본다.")
    else:
        url = d.get("url") or (qs[-1].get("url") if qs else None)
        print(f"\n(probe 산출물 {pd} 없음 — `pull` 가 가져왔어야 함. 직접: python scripts/probe.py \"{url or '<URL>'}\")")
    print(f"\n→ 원인 분류: docs/config 자동생성 실패 케이스.md 의 §번호에 매칭 → hand-config 스킬 모드 B 절차.")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "pull":
        return cmd_pull()
    if cmd == "list":
        return cmd_list()
    if cmd == "show":
        if not rest:
            print("usage: python scripts/triage.py show <slug>")
            return 2
        return cmd_show(rest[0])
    print(f"알 수 없는 명령: {cmd!r}  (pull | list | show <slug>)")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
