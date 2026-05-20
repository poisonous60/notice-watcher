"""등록된 사이트들 폴링: config 실행 → 새 글 감지 → 리포트 → 깨짐 감지 시 재-probe.

흐름(사이트별, 순차):
  1. output/poll_state/<slug>.json 읽기 (slug, url, config_path, seen_post_ids, consecutive_breakage)
  2. **구독자 체크** — bot.sqlite3 의 subscriptions 에 그 slug 가 1건도 없으면 *lurking* 모드:
     - fetch_list 는 함(seen 갱신 + 깨짐 판정 + 자가복구 위해)
     - 본문 fetch 안 함, collected/*.new.json 안 씀 → 발송 단계(deliver_due.py)가 자동 스킵 (LLM/Discord 호출 0)
     - 등록 ≠ 구독: /preview 만 한 사이트·실험 등록 사이트는 비용 0
  3. config 로 ConfigAdapter 만들어 fetch_list
     - 에러 / 0건(이전엔 글 있었는데) / 포맷 급변(post_id 모양 이상·title 대부분 빔) → 깨짐 신호
  4. 깨짐 아니면: new = 현재 post_id − seen.  (lurking 아니면) 새 글 본문 fetch(상한 --max-new-articles, polite_sleep).  seen 갱신.
  5. 깨짐이고 consecutive_breakage ≥ 2 (= 연속 2회째) → bot.sqlite3 의 jobs 큐에 reprobe 잡 enqueue. 봇 worker(bot/worker.py)가 폴링 끝난 뒤 차례로 처리. --no-reprobe 면 리포트만.
  6. 상태 파일 갱신.  결과를 output/collected/<ts>/ 에 기록.

사용:
    python scripts/poll.py
    python scripts/poll.py --sites cse.skku.edu_cse_notice... --max-new-articles 5
    python scripts/poll.py --no-reprobe          # 깨져도 재-probe 안 함(리포트만)
    python scripts/poll.py --all                 # 구독자 0 사이트도 본문 fetch (lurking 모드 끔, 기존 동작)
    python scripts/poll.py --concurrency-httpx 8 --concurrency-chromium 1   # 동시 fetch 상한
병렬: 사이트별로 동시에 fetch 한다. chromium 띄우는 strategy(playwright_html/handwritten)는 메모리 폭주 방지를 위해 별도 작은 세마포(기본 1), pure httpx 사이트는 큰 세마포(기본 8). 사이트별 print 는 fetch 완료 후 한 묶음으로 출력해 가독성 유지.
재-probe 는 폴링 중 inline 실행 X — bot.sqlite3 의 jobs 큐에 enqueue 만 함. 실제 register.py 실행은 봇 worker(bot/worker.py) 가 폴링 종료 후 chromium 락 안에서 직렬 처리.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import load_config, make_adapter  # noqa: E402
from engine.base_compat import NoticePost  # noqa: E402
from engine.tracing import start_trace, current_trace  # noqa: E402
from bot import db as bot_db  # noqa: E402
from bot.runtime_config import settings  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "output" / "poll_state"
COLLECTED_DIR = ROOT / "output" / "collected"

_STABLE_ID_RE = re.compile(r"^[\w\-./:%]{1,200}$")  # generate/validate.py:_STABLE_ID_RE 와 동기 — URL-slug-as-id 수용.
# strategy == "handwritten" 이면 adapter 이름을 보고 결정. 여기 들어있는 어댑터만 chromium sem.
_CHROMIUM_HANDWRITTEN = {"ArcaLiveAdapter"}


def _config_meta(state: dict) -> tuple[str, str]:
    """(strategy, adapter_name) 반환. 둘 다 빈 문자열 가능. 실패 시 ('', '')."""
    cp = state.get("config_path")
    if not cp:
        return "", ""
    try:
        cfg = json.loads(Path(cp).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return "", ""
    return str(cfg.get("strategy") or ""), str(cfg.get("adapter") or "")


def _uses_chromium(state: dict) -> bool:
    """이 사이트의 fetch 가 chromium 을 띄우나? (메모리 무거운 sem 결정용)."""
    strategy, adapter = _config_meta(state)
    if strategy == "playwright_html":
        return True
    if strategy == "handwritten":
        return adapter in _CHROMIUM_HANDWRITTEN
    return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cap_seen(ids: set[str], *, keep: set[str]) -> list[str]:
    """seen 집합을 상한 이하로. 최근(현재 페이지=keep)은 무조건 유지하고 나머지는 잘라낸다.
    이미 사라진 옛 글 id 를 떨어뜨려도 다시 안 올라오므로 안전. 상한 = settings.poll.seen_cap."""
    cap = settings.poll.seen_cap
    if len(ids) <= cap:
        return sorted(ids)
    keep = set(keep)
    rest = list(ids - keep)
    room = max(0, cap - len(keep))
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


async def _fetch_one(state: dict, *, page_size: int, max_new_articles: int, lurking: bool = False) -> dict:
    """한 사이트 폴링. 갱신된 state 일부 + 결과 dict 반환(상태 파일/리포트 작성은 호출 측).

    lurking=True: 구독자 0 인 사이트. fetch_list 는 하지만(seen 갱신·깨짐 판정용) 본문 fetch X, collected 파일 X.
    """
    slug = state["slug"]
    cfg_path = Path(state["config_path"])
    out = {"slug": slug, "url": state.get("url"), "status": "?", "n_posts": 0, "n_new": 0,
           "new_posts": [], "note": "", "broken": False, "lurking": lurking}

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
    tr = current_trace()
    try:
        async with make_adapter(cfg) as a:
            with tr.span("fetch_list", attrs={"slug": slug, "page_size": page_size}) as sp:
                posts = await a.fetch_list(page=1, page_size=page_size)
                sp.set_attr("n_posts", len(posts))
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
            # 구독자 0 (lurking) 이면 본문 fetch / collected 저장 / 알림 모두 건너뜀.
            # fetch_list 자체는 위에서 이미 했으니 seen 갱신 + 깨짐 판정·자가복구는 그대로 적용됨.
            if not lurking and new_posts:
                with tr.span("body_fetch_all", attrs={"slug": slug,
                                                       "n_new": len(new_posts),
                                                       "cap": max_new_articles}):
                    fetched: list[NoticePost] = []
                    body_fetched = 0
                    body_empty = 0
                    for i, p in enumerate(new_posts[:max_new_articles]):
                        if i > 0:
                            await a.polite_sleep()
                        with tr.span("body_fetch",
                                     attrs={"slug": slug, "post_id": str(p.post_id)}) as bsp:
                            try:
                                full = await a.fetch_article(p)
                                fetched.append(full)
                                body_fetched += 1
                                if not (full.content_html or "").strip():
                                    body_empty += 1
                            except Exception as e:
                                bsp.set_attr("err_short", f"{type(e).__name__}")
                                p2 = NoticePost(**{**p.to_dict(),
                                                   "raw": {**(p.raw or {}),
                                                           "fetch_error": f"{type(e).__name__}: {e}"}})
                                fetched.append(p2)
                    fetched.extend(new_posts[max_new_articles:])
                    out["new_posts"] = [p.to_dict() for p in fetched]
                    out["body_fetched"] = body_fetched
                    out["body_empty"] = body_empty
            out["status"] = "lurking" if lurking else "ok"
            out["_new_seen"] = _cap_seen(seen | cur_ids, keep=cur_ids)  # 호출 측이 state 에 반영
            return out
    except Exception as e:
        out["status"] = "breakage"
        out["note"] = f"fetch_list 에러: {type(e).__name__}: {e}"
        out["broken"] = True
        return out


def _enqueue_reprobe(state: dict) -> tuple[bool, str]:
    """bot.sqlite3 의 jobs 큐에 reprobe 잡 enqueue. (성공?, 메시지). 실제 register.py 실행은 봇 worker 가.

    같은 slug 의 pending/running reprobe 가 이미 있으면 dedupe 되어 새로 안 만듦. inline 실행 안 함 —
    폴링이 chromium_lock 풀어줘야 worker 가 진입 가능. 그래서 폴링 종료 후 차례로 처리됨.
    """
    url = state.get("url")
    slug = state.get("slug")
    if not url or not slug:
        return False, "state 에 url/slug 없음 — reprobe 잡 enqueue 불가"
    conn = bot_db.connect()
    try:
        job_id, inserted = bot_db.enqueue_job(
            conn, kind="reprobe", url=url, slug=slug, via="poll-reprobe", dedupe=True,
        )
    finally:
        conn.close()
    if inserted:
        return True, f"reprobe 잡 enqueue (#{job_id}) — 폴링 끝난 뒤 봇 worker 가 처리"
    return True, f"reprobe 잡 이미 큐에 있음 (#{job_id}) — 새로 enqueue 안 함"


def _load_states(only: set[str] | None) -> list[dict]:
    out = []
    if not STATE_DIR.exists():
        return out
    for p in sorted(STATE_DIR.glob("*.json")):
        # .FAILED.json (자동 등록 실패) / .REJECTED.json (영구 거부 marker) / .BUG.json (코드 버그 마커)
        # 셋 다 정상 state 형식 아님 — config_path 등 없음. 폴링 대상 X.
        if (p.name.endswith(".FAILED.json")
                or p.name.endswith(".REJECTED.json")
                or p.name.endswith(".BUG.json")):
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


async def _process_site(st: dict, *, page_size: int, max_new_articles: int,
                         lurking: bool, no_reprobe: bool, run_dir: Path,
                         sem_chromium: asyncio.Semaphore, sem_httpx: asyncio.Semaphore) -> tuple[list[str], tuple]:
    """한 사이트의 fetch + 결과 처리 + state 파일 쓰기 + collected 쓰기까지. (log_lines, row) 반환.

    동시 실행 가드: strategy 가 playwright_html / handwritten 이면 chromium 세마포, 아니면 httpx 세마포.
    print 안 함 — 호출 측이 묶어서 출력해 사이트 로그 가독성 유지.
    """
    slug = st["slug"]
    strategy, adapter = _config_meta(st)
    chromium = _uses_chromium(st)
    sem = sem_chromium if chromium else sem_httpx
    tag = strategy + (f":{adapter}" if strategy == "handwritten" else "")
    lines: list[str] = [
        f"=== {slug} ===  {st.get('url')} [{tag or '?'}{' (chromium)' if chromium else ''}]"
        + ("  [lurking — 구독자 0]" if lurking else "")
    ]
    tr = current_trace()
    with tr.span("poll.site", attrs={"slug": slug, "strategy": strategy,
                                       "adapter": adapter, "chromium": chromium,
                                       "lurking": lurking}) as ssp:
        async with sem:
            res = await _fetch_one(st, page_size=page_size,
                                    max_new_articles=max_new_articles, lurking=lurking)
        ssp.set_attr("n_posts", res.get("n_posts", 0))
        ssp.set_attr("n_new", res.get("n_new", 0))
        ssp.set_attr("broken", bool(res.get("broken")))
    st["last_poll_at"] = _now_iso()

    if res["broken"]:
        st["consecutive_breakage"] = int(st.get("consecutive_breakage", 0)) + 1
        st["last_status"] = res["status"]
        lines.append(f"  ⚠ 깨짐 신호 #{st['consecutive_breakage']}: {res['note']}")
        if st["consecutive_breakage"] >= settings.poll.breakage_threshold and not no_reprobe:
            # `.BUG.json` 마커 박힌 slug 은 reprobe enqueue 안 함 — bug-fix workflow 가 root cause
            # 풀고 마커 clear 할 때까지 자동 재시도 차단 (ADR 0001 의 "재시도 안 함" 계약).
            bug_marker = STATE_DIR / f"{slug}.BUG.json"
            if bug_marker.exists():
                lines.append(f"  ⏸ 연속 {st['consecutive_breakage']}회지만 BUG 마커 존재 — reprobe 스킵 (운영자 점검 대기)")
                st["last_status"] = "reprobe_skipped_bug"
                res["note"] += " | reprobe skipped (BUG marker)"
            else:
                lines.append(f"  → 연속 {st['consecutive_breakage']}회 → reprobe 잡 enqueue (봇 worker 가 폴링 후 처리)")
                ok, msg = _enqueue_reprobe(st)
                lines.append(f"  {msg}")
                if ok:
                    res["note"] += f" | {msg}"
                    st["last_status"] = "reprobe_enqueued"
                else:
                    st["last_status"] = "reprobe_enqueue_failed"
                    res["note"] += f" | {msg}"
        elif no_reprobe and st["consecutive_breakage"] >= settings.poll.breakage_threshold:
            lines.append("  (--no-reprobe — reprobe 큐 enqueue 생략, 리포트만)")
    else:
        st["consecutive_breakage"] = 0
        st["last_status"] = res["status"]  # "ok" 또는 "lurking"
        if "_new_seen" in res:
            st["seen_post_ids"] = res["_new_seen"]
        if res.get("lurking"):
            lines.append(f"  {res['n_posts']}건 / 새 글 {res['n_new']}건 (lurking — 본문 fetch·알림 생략, seen 갱신만)")
        else:
            n_fetched_bodies = sum(1 for p in res["new_posts"] if (p.get("content_html") or "").strip())
            lines.append(f"  {res['n_posts']}건 / 새 글 {res['n_new']}건 (본문 fetch {n_fetched_bodies}건)")
            for p in res["new_posts"][:5]:
                lines.append(f"    NEW {p.get('post_id')}  {p.get('published_at')}  {(p.get('title') or '')[:60]}")
            if res["new_posts"]:
                (run_dir / f"{slug}.new.json").write_text(
                    json.dumps(res["new_posts"], ensure_ascii=False, indent=2), encoding="utf-8")

            # body drift 감지 — 새 글 본문 fetch 결과 전부 빈 것이 K회 연속이면
            # 사이트가 등록 후 등급제한/로그인월 추가됐을 가능성. 직접 DM 못 부르니까
            # state 에 streak 마커 + last_status 로 dashboard 가 surface.
            body_fetched = int(res.get("body_fetched", 0))
            body_empty = int(res.get("body_empty", 0))
            if body_fetched > 0:
                if body_empty == body_fetched:
                    st["body_empty_streak"] = int(st.get("body_empty_streak", 0)) + 1
                    lines.append(f"  ⚠ 본문 fetch {body_fetched}건 전부 0자 (streak {st['body_empty_streak']})")
                else:
                    st["body_empty_streak"] = 0
                    st.pop("body_empty_drift_first_at", None)
            # 새 글 없는 사이클(body_fetched=0)은 streak 갱신·리셋 X — 마지막 신호 보존.
            # streak ≥ 3 이면 last_status 를 drift 로 유지 (line 269 의 "ok" override).
            if int(st.get("body_empty_streak", 0)) >= 3:
                st["last_status"] = "body_empty_drift"
                if not st.get("body_empty_drift_first_at"):
                    st["body_empty_drift_first_at"] = _now_iso()
                lines.append("  → body_empty_drift — 등록 후 본문 비공개화 의심. dashboard /admin/triage 확인.")

    # 상태 파일 저장 (사이트별 독립 파일 — 동시성 안전).
    # _state_path 는 안 지움 — task 예외 핸들러도 같은 경로로 minimal write 가능하게.
    st_path = Path(st["_state_path"])
    if "_new_seen" in res:
        res.pop("_new_seen", None)
    st_path.write_text(
        json.dumps({k: v for k, v in st.items() if k != "_state_path"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    row = (slug, st["last_status"], res["n_posts"], res["n_new"], res["note"])
    return lines, row


async def run(args) -> int:
    trace_attrs = {
        "sites_filter": args.sites or "(all)",
        "page_size": args.page_size,
        "max_new_articles": args.max_new_articles,
        "all_lurking_off": bool(args.all),
    }
    with start_trace("poll", attrs=trace_attrs) as tr:  # noqa: F841 (contextvar 설정용)
        return await _run_inner(args)


async def _run_inner(args) -> int:
    states = _load_states(set(args.sites) if args.sites else None)
    if not states:
        print(f"등록된 사이트 없음 ({STATE_DIR}). 먼저 `python scripts/register.py \"<URL>\"`.")
        return 0

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = COLLECTED_DIR / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    bot_conn = bot_db.connect()
    try:
        subscribed = set(bot_db.all_slugs(bot_conn))
    finally:
        bot_conn.close()

    sem_chromium = asyncio.Semaphore(args.concurrency_chromium)
    sem_httpx = asyncio.Semaphore(args.concurrency_httpx)
    print(f"[poll] 병렬 fetch — chromium sem={args.concurrency_chromium}, httpx sem={args.concurrency_httpx}, 사이트 {len(states)}개")

    tasks = [
        asyncio.create_task(_process_site(
            st, page_size=args.page_size, max_new_articles=args.max_new_articles,
            lurking=(not args.all) and (st["slug"] not in subscribed),
            no_reprobe=args.no_reprobe, run_dir=run_dir,
            sem_chromium=sem_chromium, sem_httpx=sem_httpx,
        ))
        for st in states
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    rows = []
    for st, res in zip(states, results):
        if isinstance(res, BaseException):
            # _process_site 본문 안에서 처리 못한 예외 — state 파일에 fallback 업데이트:
            # consecutive_breakage 증가시켜 reprobe 파이프라인이 인지하게.
            slug = st.get("slug", "?")
            note = f"{type(res).__name__}: {res}"
            print(f"\n=== {slug} ===")
            print(f"  ⚠ task 예외: {note}")
            st["last_poll_at"] = _now_iso()
            st["consecutive_breakage"] = int(st.get("consecutive_breakage", 0)) + 1
            st["last_status"] = "task_exception"
            sp = st.get("_state_path")
            if sp:
                try:
                    Path(sp).write_text(
                        json.dumps({k: v for k, v in st.items() if k != "_state_path"},
                                   ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except Exception as we:  # noqa: BLE001
                    print(f"  ⚠ state 파일 쓰기 실패: {we!r}")
            rows.append((slug, "task_exception", 0, 0, note))
            continue
        lines, row = res
        print()
        for line in lines:
            print(line)
        rows.append(row)

    # ADR 0006 — 이번 폴링이 발견한 새 글을 posts 캐시에 raw 박음 (summary=NULL, LLM 0).
    # 발송창(봇 1분 tick)이 나중에 lazy 요약·필터·발송. collected/ 파일을 그대로 읽어 upsert
    # (gather 후 단일 connection 순차 — async task 내 DB write 회피). INSERT OR IGNORE 라
    # 재폴링이 같은 글을 덮어쓰지 않음.
    posts_conn = bot_db.connect()
    try:
        n_cached = 0
        for f in run_dir.glob("*.new.json"):
            slug = f.name[: -len(".new.json")]
            try:
                items = json.loads(f.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                print(f"  ⚠ posts 캐시 skip {f.name}: {e!r}", file=sys.stderr)
                continue
            for post in items:
                bot_db.upsert_post(posts_conn, slug, post)
                n_cached += 1
        if n_cached:
            print(f"[poll] posts 캐시 {n_cached}건 박음")
    finally:
        posts_conn.close()

    # 요약 (사람용 summary.txt + 기계용 poll_result.json — 디버그 아티팩트, 현재 reader 없음)
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
    # 기본값은 config.toml ([poll]) 에서. CLI args 가 그걸 한 번 더 덮음.
    p.add_argument("--sites", help="쉼표 구분 slug 목록 (기본: 전부)")
    p.add_argument("--page-size", type=int, default=settings.poll.page_size)
    p.add_argument("--max-new-articles", type=int, default=settings.poll.max_new_articles,
                   help="사이트당 폴링 1회에 본문 fetch 할 새 글 상한")
    p.add_argument("--no-reprobe", action="store_true", help="깨져도 reprobe 잡 enqueue 안 함(리포트만)")
    p.add_argument("--all", action="store_true",
                   help="구독자 0 사이트도 본문 fetch + 알림(=lurking 모드 끔). 기본은 lurking — bot.sqlite3 의 subscriptions 에 1건도 없으면 fetch_list 만.")
    p.add_argument("--concurrency-httpx", type=int, default=settings.poll.concurrency_httpx,
                   help="httpx_html / httpx_json 사이트 동시 fetch 상한. 가벼우니 늘려도 메모리 부담 X")
    p.add_argument("--concurrency-chromium", type=int, default=settings.poll.concurrency_chromium,
                   help="playwright_html / ArcaLiveAdapter(handwritten) 동시 fetch 상한. chromium 1개당 RAM ~200MB+ 라 작은 박스 보호용")
    args = p.parse_args(argv)
    if args.sites:
        args.sites = [s.strip() for s in args.sites.split(",") if s.strip()]
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
