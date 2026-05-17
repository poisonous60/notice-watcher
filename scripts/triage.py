"""triage.py — 봇(N100)에서 자동 등록이 실패한 사이트들을 dev박스로 가져와 일괄 처리.

자동 등록 실패의 흔적 두 가지 (둘 다 N100 의 `~/notice-watcher/output/`):
  - `output/poll_state/<slug>.FAILED.json` : register.py 가 씀 — `reason` / `last_feedback`(=`[FAIL] <체크>` …) / `last_config`(자동 생성된 마지막 시도).
  - `output/triage_queue.jsonl`            : 봇이 `_ensure_registered` 실패 때마다 한 줄씩 append — `{ts,url,slug,via("preview"|"watch"),requested_by,register_tail}`.
성공 등록되면(자동이든 `register.py --config` 든) `_save_state` 가 둘 다 정리한다.

흐름:  python scripts/triage.py pull [--skip-later]   # N100 → 로컬 (FAILED.json + triage_queue.jsonl + 각 실패 slug 의 probe/)
       python scripts/triage.py list [--skip-later]   # 로컬에 받아온 실패 목록 표
       python scripts/triage.py show <slug>           # 그 slug 의 .FAILED.json + 요청자 + probe digest (diagnosis/list_candidates/HAR slice)
   → 그다음 hand-config 스킬 "모드 B(triage)" 로 사이트별 처리(probe 고치거나 손 config/손어댑터 작성 → register --config → N100 배포).

`--skip-later` : dashboard `/triage/failed` 에서 '나중에' 토글한 slug 제외 (`output/triage_later.json` 공유).
                  pull 시 → Later slug 의 `.FAILED.json`·`probe/<slug>/` 로컬에서 제거(다음 호출에서도 안 누적).
                  list 시 → Later slug 행 안 보임.
                  show <slug> 는 명시 호출이라 Later 라도 통과.

N100 호스트: 환경변수 `DEPLOY_HOST`(기본 `<user>@<host>` — Tailscale MagicDNS) / `DEPLOY_PATH`(기본 `~/notice-watcher`).
  Tailscale 이 LAN/외부 양쪽에서 라우팅 — IP 변동 무관. LAN IP `aaaa@<lan-ip>` 도 집에서는 OK.
  ※ ssh/scp 가 PATH 에 있어야 함(Windows 10+ 기본 포함).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
STATE_DIR = OUTPUT / "poll_state"
QUEUE = OUTPUT / "triage_queue.jsonl"
PROBE_DIR = OUTPUT / "probe"
LATER_STORE = OUTPUT / "triage_later.json"  # dashboard `/triage/failed` 의 '나중에' 토글 (dev box only, gitignored)

DEPLOY_HOST = os.environ.get("DEPLOY_HOST", "<user>@<host>")
DEPLOY_PATH = os.environ.get("DEPLOY_PATH", "~/notice-watcher")

_FAILED_SUFFIX = ".FAILED.json"


def _load_later() -> set[str]:
    """dashboard/triage_later.py 와 같은 파일. 부재 OK."""
    if not LATER_STORE.exists():
        return set()
    try:
        d = json.loads(LATER_STORE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {str(s) for s in (d.get("later") or []) if s}


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


def _truncate(s, n: int = 100) -> str:
    s = "" if s is None else str(s)
    s = s.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def _load_probe_json(pd: Path, name: str) -> dict | list | None:
    fp = pd / name
    if not fp.exists():
        return None
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _print_list_candidates_digest(pd: Path) -> None:
    """§2b/§2c 판정 anchor — first_article_url + 상위 후보 한 줄씩."""
    lc = _load_probe_json(pd, "list_candidates.json")
    if not isinstance(lc, dict):
        return
    print(f"\n=== list_candidates.json digest ===")
    fau = lc.get("first_article_url")
    print(f"  first_article_url : {_truncate(fau or '(없음 — §2b 신호)', 140)}")
    html = lc.get("html_repeating_patterns") or []
    api = lc.get("traffic_json_api_candidates") or []
    hyd = lc.get("hydration_list_candidates") or []
    inline = lc.get("inline_js_data_candidates") or []
    print(f"  후보 수            : html={len(html)} api={len(api)} hydration={len(hyd)} inline_js={len(inline)}")
    for i, p in enumerate(html[:3], 1):
        if not isinstance(p, dict):
            continue
        sel = _truncate(p.get("selector"), 60)
        cc = p.get("child_count")
        ft = _truncate(p.get("first_text"), 50)
        sample = _truncate(p.get("sample_url"), 80)
        print(f"  html[{i}] cc={cc} sel={sel}")
        print(f"         text={ft}")
        print(f"         sample={sample}")
    for i, p in enumerate(api[:2], 1):
        if not isinstance(p, dict):
            continue
        print(f"  api[{i}] url={_truncate(p.get('url'), 90)}  count_guess={p.get('count_guess')}")


def _print_diagnosis_digest(pd: Path) -> None:
    d = _load_probe_json(pd, "diagnosis.json")
    if not isinstance(d, dict):
        return
    print(f"\n=== diagnosis.json digest ===")
    keys = ("verdict", "recommended_strategy", "recommended_headers", "recommended_polling_interval_sec", "list_candidates_summary", "article_entry_ok")
    for k in keys:
        if k in d:
            print(f"  {k:<36}: {_truncate(d.get(k), 200)}")
    notes = d.get("notes") or []
    if isinstance(notes, list) and notes:
        print(f"  notes ({min(3, len(notes))}/{len(notes)}):")
        for n in notes[:3]:
            print(f"    - {_truncate(n, 180)}")


def _print_har_digest(pd: Path) -> None:
    """4xx/5xx + 차단 sniff. HAR 큰 파일이라 파싱 1회로 끝."""
    fp = pd / "traffic.har"
    if not fp.exists():
        return
    try:
        d = json.loads(fp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    entries = ((d.get("log") or {}).get("entries")) or []
    if not entries:
        return
    n = len(entries)
    err4_count = err5_count = 0
    err4_first = err5_first = None  # 첫 sample 만 보관 — 큰 HAR 에서 list 누적 안 함
    for e in entries:
        st = ((e.get("response") or {}).get("status")) or 0
        if 400 <= st < 500:
            err4_count += 1
            if err4_first is None:
                err4_first = (st, (e.get("request") or {}).get("url", ""))
        elif st >= 500:
            err5_count += 1
            if err5_first is None:
                err5_first = (st, (e.get("request") or {}).get("url", ""))
    print(f"\n=== traffic.har digest ===")
    print(f"  총 요청: {n}   4xx: {err4_count}   5xx: {err5_count}")
    if err4_first:
        st, url = err4_first
        print(f"  첫 4xx: {st}  {_truncate(url, 120)}")
    if err5_first:
        st, url = err5_first
        print(f"  첫 5xx: {st}  {_truncate(url, 120)}")


# --------------------------------------------------------------------------- #
def cmd_pull(skip_later: bool = False) -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    later = _load_later() if skip_later else set()

    # 1a) N100 의 현재 FAILED.json slug + triage_queue.jsonl 존재 여부를 *한 번의 ssh* 로 받는다 —
    # local 의 stale (N100 에서 이미 REJECTED 로 전환됐는데 옛 FAILED 가 local 에 남은 것) 자동 정리.
    # scp 는 reverse-delete 안 함 → 명시 sync 필요.
    #
    # 사전 안전 장치 — ssh 실패 (네트워크/권한/DEPLOY_PATH 오타) 시 remote 가 empty 라 *오해* 해서 모든 local
    # FAILED 를 stale 로 판정해 일괄 삭제하는 사고 방지. 두 sentinel (__OK__/__QOK__) 가 *둘 다* 출력에
    # 있어야 remote 응답이 신뢰 가능. 하나라도 없으면 sync delete 자체를 skip — local 보존이 default-safe.
    sentinel_ok = "__TRIAGE_PULL_OK__"
    sentinel_qok = "__TRIAGE_QUEUE_OK__"
    sentinel_qmiss = "__TRIAGE_QUEUE_MISSING__"
    remote_cmd = (
        f"cd {DEPLOY_PATH} && "
        f"(ls output/poll_state/*{_FAILED_SUFFIX} 2>/dev/null; echo {sentinel_ok}) && "
        f"(test -f output/triage_queue.jsonl && echo {sentinel_qok} || echo {sentinel_qmiss})"
    )
    rc_ls, out_ls = _run(["ssh", DEPLOY_HOST, remote_cmd])
    remote_response_trusted = (rc_ls == 0 and sentinel_ok in out_ls
                                and (sentinel_qok in out_ls or sentinel_qmiss in out_ls))
    remote_failed: set[str] = set()
    remote_queue_missing = False
    if remote_response_trusted:
        for line in out_ls.splitlines():
            line = line.strip()
            if not line or line == sentinel_ok or line.startswith("__TRIAGE_"):
                continue
            name = Path(line).name
            if name.endswith(_FAILED_SUFFIX):
                remote_failed.add(name)
        remote_queue_missing = sentinel_qmiss in out_ls
    else:
        sys.stderr.write(f"[triage pull] ⚠ remote 응답 검증 실패 (rc={rc_ls}, sentinel 누락) — "
                         f"sync delete skip, local 보존. ssh/DEPLOY_HOST/DEPLOY_PATH 확인.\n")

    pruned_stale = 0
    pruned_stale_slugs: list[str] = []
    if remote_response_trusted:
        for fp in STATE_DIR.glob(f"*{_FAILED_SUFFIX}"):
            if fp.name not in remote_failed:
                try:
                    fp.unlink()
                    pruned_stale += 1
                    pruned_stale_slugs.append(fp.name[: -len(_FAILED_SUFFIX)])
                except OSError as e:
                    sys.stderr.write(f"[triage pull] stale {fp.name} 삭제 실패: {e}\n")
        # triage_queue 도 reverse-delete: N100 에 파일 자체가 사라졌으면 local 도 삭제 (N100 _prune_triage_queue
        # 가 last entry 지우면 파일 unlink 함 — local 에만 잔재 시 영구 stale 위험).
        if remote_queue_missing and QUEUE.exists():
            try:
                QUEUE.unlink()
            except OSError as e:
                sys.stderr.write(f"[triage pull] stale triage_queue.jsonl 삭제 실패: {e}\n")

    # 1b) <slug>.FAILED.json 들 — 원격 셸이 glob 확장. 매치 0개면 scp 가 비0 으로 끝남(에러 아님).
    rc, out = _run(["scp", "-q", f"{DEPLOY_HOST}:{DEPLOY_PATH}/output/poll_state/*{_FAILED_SUFFIX}", f"{STATE_DIR}{os.sep}"])
    if rc != 0 and not any(s in out for s in ("No such file", "not a regular file", "matches no files")):
        sys.stderr.write(f"[triage pull] FAILED.json 가져오기 경고: {out}\n")

    # 1b) skip-later: glob 받은 뒤 Later slug 의 marker 즉시 삭제 (selective scp 불가, 받은 뒤 정리)
    pruned_failed = 0
    if later:
        for slug in list(later):
            fp = STATE_DIR / f"{slug}{_FAILED_SUFFIX}"
            if fp.exists():
                try:
                    fp.unlink()
                    pruned_failed += 1
                except OSError as e:
                    sys.stderr.write(f"[triage pull] Later {slug}.FAILED.json 삭제 실패: {e}\n")

    # 2) triage_queue.jsonl (없을 수 있음)
    _run(["scp", "-q", f"{DEPLOY_HOST}:{DEPLOY_PATH}/output/triage_queue.jsonl", str(QUEUE)])

    # 3) 각 실패 slug 의 probe 산출물 디렉토리 (진단 재료). Later 는 건너뜀 + 이미 받은 거 정리.
    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    slugs = _failed_slugs()
    pruned_probe = 0
    for slug in slugs:
        if slug in later:
            continue
        _run(["scp", "-rq", f"{DEPLOY_HOST}:{DEPLOY_PATH}/output/probe/{slug}", f"{PROBE_DIR}{os.sep}"])
    if later:
        for slug in later:
            pd = PROBE_DIR / slug
            if pd.exists():
                try:
                    shutil.rmtree(pd)
                    pruned_probe += 1
                except OSError as e:
                    sys.stderr.write(f"[triage pull] Later {slug} probe/ 삭제 실패: {e}\n")

    # 3b) probe/ stale 정리 — *방금 prune 된 stale FAILED slug 의 probe 디렉토리만* 삭제.
    # 다른 probe/ 디렉토리(smoke fixture, 성공 등록 사이트 probe 등)는 건드리지 않음.
    pruned_stale_probe = 0
    for slug in pruned_stale_slugs:
        pd = PROBE_DIR / slug
        if pd.exists() and pd.is_dir():
            try:
                shutil.rmtree(pd)
                pruned_stale_probe += 1
            except OSError as e:
                sys.stderr.write(f"[triage pull] stale probe/{slug} 삭제 실패: {e}\n")

    nq = len({e.get("slug") for e in _read_queue()})
    print(f"[triage pull] {DEPLOY_HOST}:{DEPLOY_PATH}/output → {OUTPUT}")
    print(f"  FAILED.json: {len(slugs)}건   triage_queue slug: {nq}건   probe 디렉토리: {sum(1 for s in slugs if (PROBE_DIR / s).exists())}개")
    if pruned_stale or pruned_stale_probe:
        print(f"  stale 정리 (N100 에서 이미 REJECTED/등록 완료): FAILED.json {pruned_stale}건 / probe {pruned_stale_probe}개")
    if later:
        print(f"  Later 제외: FAILED.json {pruned_failed}건 / probe {pruned_probe}개 정리   (`output/triage_later.json` — dashboard 토글)")
    print("  → `python scripts/triage.py list`")
    return 0


def cmd_list(skip_later: bool = False) -> int:
    slugs = set(_failed_slugs())
    q = _read_queue()
    q_by_slug: dict[str, list[dict]] = {}
    for e in q:
        q_by_slug.setdefault(str(e.get("slug") or ""), []).append(e)
    all_slugs = sorted(slugs | set(k for k in q_by_slug if k))
    later_skipped = 0
    if skip_later:
        later = _load_later()
        before = len(all_slugs)
        all_slugs = [s for s in all_slugs if s not in later]
        later_skipped = before - len(all_slugs)
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
    if later_skipped:
        print(f"  Later 제외: {later_skipped}건 숨김 (dashboard `/triage/failed` 의 '나중에' 토글).")
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
        # §2 분기 anchor 들 — full file Read 대신 핵심 slice 만 자동 표면화 (claude skim 방지 + 누적 토큰 절약).
        _print_diagnosis_digest(pd)
        _print_list_candidates_digest(pd)
        _print_har_digest(pd)
        print(f"\n=== probe 산출물 디렉토리: {pd} ===")
        print(f"  (위 digest 만으로 부족하면: summary.txt / article_candidates.json / list.html / article.html 등을 Read)")
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
    skip_later = False
    if "--skip-later" in rest:
        skip_later = True
        rest = [a for a in rest if a != "--skip-later"]
    if cmd == "pull":
        return cmd_pull(skip_later=skip_later)
    if cmd == "list":
        return cmd_list(skip_later=skip_later)
    if cmd == "show":
        if not rest:
            print("usage: python scripts/triage.py show <slug>")
            return 2
        return cmd_show(rest[0])
    print(f"알 수 없는 명령: {cmd!r}  (pull | list | show <slug>)  [--skip-later]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
