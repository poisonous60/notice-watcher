"""등록된 사이트들 폴링: config 실행 → 새 글 감지 → 리포트 → 깨짐 감지 시 재-probe.

흐름(사이트별, 순차):
  1. output/poll_state/<slug>.json 읽기 (slug, url, config_path, seen_post_ids, consecutive_breakage)
  2. config 로 ConfigAdapter 만들어 fetch_list
     - 에러 / 0건(이전엔 글 있었는데) / 포맷 급변(post_id 모양 이상·title 대부분 빔) → 깨짐 신호
  3. 깨짐 아니면: new = 현재 post_id − seen.  새 글 본문 fetch(상한 --max-new-articles, polite_sleep).  seen 갱신.
  4. 깨짐이고 consecutive_breakage ≥ 2 (= 연속 2회째) → register.py 재실행(re-probe + 재생성, 옛 config 는 .bak 보관, 실패 시 복구).  --no-reprobe 면 리포트만.
  5. 상태 파일 갱신.  결과를 output/collected/<ts>/ 에 기록.

사용:
    python scripts/poll.py
    python scripts/poll.py --sites cse.skku.edu_cse_notice... --max-new-articles 5
    python scripts/poll.py --no-reprobe          # 깨져도 재-probe 안 함(리포트만)
필요(재-probe 시): Gemini API 키 (GEMINI_API_KEYS/GEMINI_API_KEY env 또는 GEMINI_API_KEY.md).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import load_config, make_adapter  # noqa: E402
from engine.base_compat import NoticePost  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "output" / "poll_state"
COLLECTED_DIR = ROOT / "output" / "collected"

_STABLE_ID_RE = re.compile(r"^[\w\-./:%]{1,64}$")
_BREAKAGE_THRESHOLD = 2  # 연속 N회 깨지면 재-probe


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_SEEN_CAP = 5000  # seen_post_ids 무한 증가 방지 상한


def _cap_seen(ids: set[str], *, keep: set[str]) -> list[str]:
    """seen 집합을 상한 이하로. 최근(현재 페이지=keep)은 무조건 유지하고 나머지는 잘라낸다.
    이미 사라진 옛 글 id 를 떨어뜨려도 다시 안 올라오므로 안전."""
    if len(ids) <= _SEEN_CAP:
        return sorted(ids)
    keep = set(keep)
    rest = list(ids - keep)
    room = max(0, _SEEN_CAP - len(keep))
    return sorted(keep | set(rest[:room]))


def _looks_broken(posts: list[NoticePost]) -> tuple[bool, str]:
    if not posts:
        return True, "0건 (이전엔 글이 있었음)"
    bad_id = [p.post_id for p in posts if not _STABLE_ID_RE.match(str(p.post_id))]
    if bad_id:
        return True, f"post_id 모양 이상(공백 등): {bad_id[:5]}"
    empty_titles = sum(1 for p in posts if not (p.title and p.title.strip()))
    if empty_titles > len(posts) // 2:
        return True, f"title 이 대부분 빔 ({empty_titles}/{len(posts)})"
    return False, ""


async def _fetch_one(state: dict, *, page_size: int, max_new_articles: int) -> dict:
    """한 사이트 폴링. 갱신된 state 일부 + 결과 dict 반환(상태 파일/리포트 작성은 호출 측)."""
    slug = state["slug"]
    cfg_path = Path(state["config_path"])
    out = {"slug": slug, "url": state.get("url"), "status": "?", "n_posts": 0, "n_new": 0,
           "new_posts": [], "note": "", "broken": False}

    if not cfg_path.exists():
        out["status"] = "error"
        out["note"] = f"config 파일 없음: {cfg_path}"
        out["broken"] = True
        return out
    try:
        cfg = load_config(cfg_path)
    except Exception as e:
        out["status"] = "error"
        out["note"] = f"config 로드 실패: {e}"
        out["broken"] = True
        return out

    seen = set(state.get("seen_post_ids") or [])
    had_baseline = int(state.get("n_baseline", 0) or 0) > 0  # 등록 시점에 글이 있었나 — 0건 판정 기준
    try:
        async with make_adapter(cfg) as a:
            posts = await a.fetch_list(page=1, page_size=page_size)
            out["n_posts"] = len(posts)
            broken, why = _looks_broken(posts) if had_baseline else (False, "")
            if broken:
                out["status"] = "breakage"
                out["note"] = why
                out["broken"] = True
                return out
            cur_ids = {str(p.post_id) for p in posts}
            new_posts = [p for p in posts if str(p.post_id) not in seen]
            out["n_new"] = len(new_posts)
            # 새 글 본문 fetch (상한, polite_sleep)
            fetched: list[NoticePost] = []
            for i, p in enumerate(new_posts[:max_new_articles]):
                if i > 0:
                    await a.polite_sleep()
                try:
                    fetched.append(await a.fetch_article(p))
                except Exception as e:
                    p2 = NoticePost(**{**p.to_dict(), "raw": {**(p.raw or {}), "fetch_error": f"{type(e).__name__}: {e}"}})
                    fetched.append(p2)
            # 상한 넘은 새 글은 본문 없이
            fetched.extend(new_posts[max_new_articles:])
            out["new_posts"] = [p.to_dict() for p in fetched]
            out["status"] = "ok"
            out["_new_seen"] = _cap_seen(seen | cur_ids, keep=cur_ids)  # 호출 측이 state 에 반영
            return out
    except Exception as e:
        out["status"] = "breakage"
        out["note"] = f"fetch_list 에러: {type(e).__name__}: {e}"
        out["broken"] = True
        return out


def _reprobe(state: dict, *, model: str | None) -> tuple[bool, str]:
    """register.py 재실행(re-probe + 재생성). 옛 config 는 .bak 보관, 실패 시 복구. (성공?, 메시지)."""
    url = state.get("url")
    cfg_path = Path(state["config_path"])
    if not url:
        return False, "state 에 url 없음 — 재-probe 불가"
    bak = cfg_path.with_suffix(cfg_path.suffix + ".bak")
    if cfg_path.exists():
        shutil.copy2(cfg_path, bak)
    cmd = [sys.executable, str(ROOT / "scripts" / "register.py"), url, "--out", str(cfg_path), "--force"]
    if model:
        cmd += ["--model", model]
    env_note = ""
    rc = subprocess.call(cmd)
    if rc == 0:
        return True, f"재-probe + 재생성 성공 (옛 config → {bak.name})"
    # 실패 → 복구
    if bak.exists():
        shutil.copy2(bak, cfg_path)
        env_note = " (옛 config 복구함)"
    return False, f"재-probe 실패 (rc={rc}){env_note} — 유지보수자 확인 필요"


def _load_states(only: set[str] | None) -> list[dict]:
    out = []
    if not STATE_DIR.exists():
        return out
    for p in sorted(STATE_DIR.glob("*.json")):
        if p.name.endswith(".FAILED.json"):
            continue
        try:
            st = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        st["_state_path"] = str(p)
        if only and st.get("slug") not in only:
            continue
        out.append(st)
    return out


async def run(args) -> int:
    states = _load_states(set(args.sites) if args.sites else None)
    if not states:
        print(f"등록된 사이트 없음 ({STATE_DIR}). 먼저 `python scripts/register.py \"<URL>\"`.")
        return 0

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = COLLECTED_DIR / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for st in states:
        slug = st["slug"]
        print(f"\n=== {slug} ===  {st.get('url')}")
        res = await _fetch_one(st, page_size=args.page_size, max_new_articles=args.max_new_articles)
        st["last_poll_at"] = _now_iso()

        if res["broken"]:
            st["consecutive_breakage"] = int(st.get("consecutive_breakage", 0)) + 1
            st["last_status"] = res["status"]
            print(f"  ⚠ 깨짐 신호 #{st['consecutive_breakage']}: {res['note']}")
            if st["consecutive_breakage"] >= _BREAKAGE_THRESHOLD and not args.no_reprobe:
                print(f"  → 연속 {st['consecutive_breakage']}회 → 재-probe + 재생성 시도")
                ok, msg = _reprobe(st, model=args.model)
                print(f"  {msg}")
                if ok:
                    res["note"] += f" | {msg}"
                    # register.py 가 새 state 파일을 썼음(baseline=현재 글) — 그걸 기준으로 삼되 poll 메타만 덧씌움
                    sp = st["_state_path"]
                    try:
                        fresh = json.loads(Path(sp).read_text(encoding="utf-8"))
                        fresh["_state_path"] = sp
                        st = fresh
                    except Exception:
                        pass
                    st["consecutive_breakage"] = 0
                    st["last_status"] = "reprobed_ok"
                    st["last_poll_at"] = _now_iso()
                else:
                    st["last_status"] = "reprobe_failed"
                    res["note"] += f" | {msg}"
            elif args.no_reprobe and st["consecutive_breakage"] >= _BREAKAGE_THRESHOLD:
                print("  (--no-reprobe — 재-probe 생략, 리포트만)")
        else:
            st["consecutive_breakage"] = 0
            st["last_status"] = "ok"
            if "_new_seen" in res:
                st["seen_post_ids"] = res["_new_seen"]
            n_fetched_bodies = sum(1 for p in res["new_posts"] if (p.get("content_html") or "").strip())
            print(f"  {res['n_posts']}건 / 새 글 {res['n_new']}건 (본문 fetch {n_fetched_bodies}건)")
            for p in res["new_posts"][:5]:
                print(f"    NEW {p.get('post_id')}  {p.get('published_at')}  {(p.get('title') or '')[:60]}")
            if res["new_posts"]:
                (run_dir / f"{slug}.new.json").write_text(
                    json.dumps(res["new_posts"], ensure_ascii=False, indent=2), encoding="utf-8")

        # 상태 파일 저장
        st_path = Path(st.pop("_state_path"))
        if "_new_seen" in res:
            res.pop("_new_seen", None)
        st_path.write_text(json.dumps({k: v for k, v in st.items()}, ensure_ascii=False, indent=2), encoding="utf-8")
        rows.append((slug, st["last_status"], res["n_posts"], res["n_new"], res["note"]))

    # 요약 (사람용 summary.txt + 기계용 poll_result.json — notify.py 의 heartbeat 가 읽음)
    lines = [f"[poll {ts}]", ""]
    for slug, status, npos, nnew, note in rows:
        lines.append(f"  {slug}\n      status={status}  posts={npos}  new={nnew}  {note}")
    text = "\n".join(lines) + "\n"
    (run_dir / "summary.txt").write_text(text, encoding="utf-8")
    (run_dir / "poll_result.json").write_text(
        json.dumps({"ts": ts, "polled_at": _now_iso(),
                    "sites": [{"slug": s, "status": st, "n_posts": np, "n_new": nn}
                              for s, st, np, nn, _ in rows]},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    print("\n" + text)
    print(f"→ {run_dir}")
    return 0


def main(argv) -> int:
    p = argparse.ArgumentParser(description="등록된 사이트 폴링 (새 글 감지 + 깨짐 시 재-probe)")
    p.add_argument("--sites", help="쉼표 구분 slug 목록 (기본: 전부)")
    p.add_argument("--page-size", type=int, default=30)
    p.add_argument("--max-new-articles", type=int, default=10, help="사이트당 폴링 1회에 본문 fetch 할 새 글 상한")
    p.add_argument("--no-reprobe", action="store_true", help="깨져도 재-probe 안 함(리포트만)")
    p.add_argument("--model", help="재-probe 시 gemini 모델")
    args = p.parse_args(argv)
    if args.sites:
        args.sites = [s.strip() for s in args.sites.split(",") if s.strip()]
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
