"""등록된 사이트들 폴링: config 실행 → 새 글 감지 → 리포트 → 깨짐 감지 시 재-probe.

ADR 0017 (runs 추적 + 영속화 검증):
  - `poll_runs` 1 row / 폴링 1회. 시작 시 INSERT(status='running'), 끝 시 UPDATE(status='done').
    process 죽으면 다음 run 의 reaper 가 'crashed' 박음.
  - `poll_site_runs` 1 row / 사이트 1회 (finish 시점 INSERT). status·n_attempted_unique·
    n_inserted·n_present_after 같이 박음.
  - persist 검증: 새 글 INSERT 후 SELECT 로 *실제 박힌* 글 카운트. mismatch (n_present_after !=
    n_attempted_unique) 시 status='persist_mismatch' + missing id note + **seen 에서 missing 제외**.
  - 모든 tracking helper 는 best-effort — fail 해도 폴링 본 흐름 영향 X. ADR 0017 §2f.

ADR 0016 (per-site isolation):
  - 사이트 1개당 `asyncio.wait_for(_process_site, timeout=POLL_SITE_TIMEOUT_S=180s)` wall cap.
    초과 시 그 사이트만 `last_status="poll_timeout"` 죽이고 나머지 사이트는 그대로 진행
    (기존엔 `asyncio.gather` 가 끝나기를 기다린 뒤 일괄 posts 캐시 박는 구조라 1개 hang =
     1000개 글 lost. 2026-05-25 incident 후 fix).
  - posts 캐시 sqlite upsert 는 `_process_site` 안에서 *progressive*. ordering:
    ① .new.json → ② sqlite INSERT OR IGNORE (사이트당 1 batch commit) → ③ seen_post_ids
    in-memory 갱신 → ④ state.json 디스크 flush. crash safe (state.json 의 seen 은 sqlite
    박힌 글만 인정).
  - single `sqlite3.Connection` + `asyncio.Lock` 으로 writer 직렬화 (WAL).
  - stderr 에 `[poll] start <slug>` / `[poll] done <slug> t=Xms` / `[poll] TIMEOUT <slug>`
    1줄씩. 다음 hang 진단용. `state.last_poll_duration_ms` 박음.

흐름(사이트별, 동시):
  1. output/poll_state/<slug>.json 읽기 (slug, url, config_path, seen_post_ids, consecutive_breakage)
  2. **구독자 체크** — bot.sqlite3 의 subscriptions 에 그 slug 가 1건도 없으면 *완전 skip*
     (2026-05-25 사용자 결정. 이전 default = "lurking" = fetch_list 만 했음 — chromium
     sem=1 직렬 줄에서 wall 412s 의 99% 잡아먹음. seen 갱신·자가복구 가치 ≈ 0).
     - `--all` 또는 `--sites <slug>` 로 명시 시 lurking 도 포함 — 디버그·재계산용.
     - lurking 모드 안에서도 본문 fetch 는 안 함, collected/*.new.json 안 씀 (옛 동작 유지).
  3. config 로 ConfigAdapter 만들어 fetch_list
     - 에러 / 0건(이전엔 글 있었는데) / 포맷 급변(post_id 모양 이상·title 대부분 빔) → 깨짐 신호
  4. 깨짐 아니면: new = 현재 post_id − seen.  (lurking 아니면) 새 글 본문 fetch(상한 --max-new-articles, polite_sleep).
     ADR 0016 ordering 따라 .new.json → sqlite upsert → seen → state.json.
  5. 깨짐이고 consecutive_breakage ≥ 2 (= 연속 2회째) → bot.sqlite3 의 jobs 큐에 reprobe 잡 enqueue. 봇 worker(bot/worker.py)가 폴링 끝난 뒤 차례로 처리. --no-reprobe 면 리포트만.

사용:
    python scripts/poll.py
    python scripts/poll.py --sites cse.skku.edu_cse_notice... --max-new-articles 5
    python scripts/poll.py --no-reprobe          # 깨져도 재-probe 안 함(리포트만)
    python scripts/poll.py --all                 # 구독자 0 사이트도 본문 fetch (lurking 모드 끔, 기존 동작)
    python scripts/poll.py --concurrency-httpx 8 --concurrency-chromium 1   # 동시 fetch 상한
    python scripts/poll.py --site-timeout 300    # 사이트별 wall timeout override (기본 180s)
병렬: 사이트별로 동시에 fetch 한다. chromium 띄우는 strategy(playwright_html/handwritten)는 메모리 폭주 방지를 위해 별도 작은 세마포(기본 1), pure httpx 사이트는 큰 세마포(기본 8). 사이트별 print 는 fetch 완료 후 한 묶음으로 출력해 가독성 유지.
재-probe 는 폴링 중 inline 실행 X — bot.sqlite3 의 jobs 큐에 enqueue 만 함. 실제 register.py 실행은 봇 worker(bot/worker.py) 가 폴링 종료 후 chromium 락 안에서 직렬 처리.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
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
SITEMAP_LASTMOD_LOG = ROOT / "output" / "sitemap_lastmod_log.jsonl"
PROBE_DIR = ROOT / "output" / "probe"

_STABLE_ID_RE = re.compile(r"^[\w\-./:%,]{1,200}$")  # generate/validate.py:_STABLE_ID_RE 와 동기 — URL-slug-as-id 수용 + Atom RFC 4151 tag URI (`,` 날짜 구분자).
# strategy == "handwritten" 이면 adapter 이름을 보고 결정. 여기 들어있는 어댑터만 chromium sem.
_CHROMIUM_HANDWRITTEN = {"ArcaLiveAdapter", "IdxPressReleaseAdapter"}

# ADR 0016 — 사이트 1개당 wall timeout. 정상 폴링 ≪ 30s, anti-bot 사이트 ≈ 17s.
# 180s = 정상의 6×, anti-bot 의 10×. 이 cap 넘으면 그 사이트만 poll_timeout 로 죽이고
# 나머지 사이트는 그대로 진행 — 1개 hang 으로 1000개 폴링 결과 lost 막음.
POLL_SITE_TIMEOUT_S = 180


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


_LASTMOD_RE = re.compile(r"<lastmod[^>]*>([^<]+)</lastmod>", re.IGNORECASE)
_SITEMAP_INDEX_RE = re.compile(r"<sitemapindex\b", re.IGNORECASE)
_LASTMOD_BODY_CAP = 8192  # 진짜 download cap — server Range 무시해도 안 넘김.


def _normalize_lastmod(s: str | None) -> str | None:
    """timestamp 비교용 정규화 — UTC ISO 로. parse 실패 시 strip 만.

    XML <lastmod> = W3C datetime (`2026-05-24T01:23:45+09:00` 또는 `2026-05-24`).
    HTTP Last-Modified = RFC7231 (`Sun, 24 May 2026 01:23:45 GMT`). raw 비교는 timezone/precision
    차이로 false negative — 2026-05-24 codex 2차 리뷰 LOW.
    """
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    try:
        from datetime import datetime, timezone
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(s)
        if dt is None:
            return s
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return s


async def _check_sitemap_lastmod(state: dict) -> dict | None:
    """observe-only sitemap lastmod check (2026-05-24 A 묶음 #2).

    매 cron 사이클에 각 site 당 1회 sitemap.xml Range GET (~2KB) → 첫 <lastmod>
    추출 → state 의 이전값과 비교 → would_skip 판정 + log line 만 기록.

    **실제 fetch_list skip 안 함** — 1주 logging 후 false_skip_pct/wasted_fetch_pct
    측정으로 활성화 여부 결정 (`experiments/sitemap-lastmod-bench/observe_only_sketch.md`).

    fail-soft: 어떤 오류든 None 또는 {"lastmod_source":"error",...} — fetch_list 흐름 영향 X.
    """
    slug = state.get("slug")
    if not slug:
        return None
    sitemap_path = PROBE_DIR / slug / "sitemap.json"
    if not sitemap_path.exists():
        return None
    try:
        sm = json.loads(sitemap_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    tried = sm.get("sitemap_urls_tried") or []
    if not tried:
        return None
    sitemap_url = tried[0]
    prev = state.get("sitemap_lastmod_last_seen")
    obs = {"sitemap_url": sitemap_url, "prev_lastmod": prev,
           "current_lastmod": None, "lastmod_source": "missing",
           "would_skip": False, "is_sitemap_index": False, "error": None}
    try:
        import httpx
        # stream + aiter_bytes 로 진짜 download cap (Range 무시 서버 대비). 이전 `r.content[:8192]`
        # 는 slice 만 — full body 다운로드 후 잘랐음. 2026-05-24 codex 2차 리뷰 MED.
        async with httpx.AsyncClient(timeout=2.0, follow_redirects=True) as c:
            async with c.stream("GET", sitemap_url,
                                headers={"Range": f"bytes=0-{_LASTMOD_BODY_CAP - 1}",
                                         "User-Agent": "notice-watcher/0 (+lastmod-observe)"}) as r:
                buf = bytearray()
                async for chunk in r.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) >= _LASTMOD_BODY_CAP:
                        break
                http_last_modified = r.headers.get("last-modified")
        body_bytes = bytes(buf[:_LASTMOD_BODY_CAP])
        body = body_bytes.decode("utf-8", errors="replace") if body_bytes else ""
        # sitemap index 면 child sitemap 의 timestamp 가 content URL timestamp 아님 — would_skip
        # 에서 제외 (metric 오염 방지). 별 lastmod_source 라벨로 분리. 2026-05-24 codex 2차 리뷰 LOW.
        is_index = bool(_SITEMAP_INDEX_RE.search(body[:1024]))
        obs["is_sitemap_index"] = is_index
        m = _LASTMOD_RE.search(body)
        if m:
            obs["current_lastmod"] = m.group(1).strip()
            obs["lastmod_source"] = "sitemap_index_child_lastmod" if is_index else "first_url_lastmod"
        elif http_last_modified:
            obs["current_lastmod"] = http_last_modified.strip()
            obs["lastmod_source"] = "http_last_modified"
        # would_skip — sitemap index 파생 timestamp 는 제외 (child sitemap 변경 ≠ 새 글).
        # normalize 후 비교 — W3C vs RFC7231 timezone/precision 차이로 false negative 차단.
        if prev and obs["current_lastmod"] and not is_index:
            obs["would_skip"] = (_normalize_lastmod(prev) == _normalize_lastmod(obs["current_lastmod"]))
    except Exception as exc:
        obs["lastmod_source"] = "error"
        obs["error"] = f"{type(exc).__name__}: {exc}"
    return obs


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


def _maybe_save_broken(slug: str, st: dict, *, note: str = "",
                        log_lines: list[str] | None = None) -> None:
    """BROKEN health sidecar — `consecutive_breakage >= broken_threshold` + 차단 마커 없음 → `_save_broken`.

    호출자: (1) _process_site 의 res['broken'] 분기, (2) _site_with_timeout 의 chromium_lock_timeout
    fallback, (3) _run_inner 의 wall-timeout / task_exception fallback. 같은 가드 (우선순위 마커가
    있으면 BROKEN 안 박음, _save_broken 자체는 가드 안 하므로 호출자 책임) 적용.

    `is_blocked` 차단 X — polling/reprobe/delivery 그대로 살아있고, deliver_due 가 status notice
    자리에 "❗ 깨졌어요" 표시. 자체 복구되면 다음 reprobe rc=0 또는 정상 poll 가 cb=0 + BROKEN unlink.
    """
    cb = int(st.get("consecutive_breakage", 0) or 0)
    if cb < int(settings.poll.broken_threshold or 6):
        return
    has_blocking = any(
        (STATE_DIR / f"{slug}.{k}.json").exists()
        for k in ("FAILED", "REJECTED", "BUG")
    )
    if has_blocking:
        return
    try:
        from scripts.register import _save_broken
        _save_broken(slug, st.get("url", "") or "",
                      cb=cb,
                      last_status=str(st.get("last_status", "") or ""),
                      last_note=str(note or ""))
        if log_lines is not None:
            log_lines.append(f"  ❗ BROKEN sidecar 박음 (cb={cb} ≥ {settings.poll.broken_threshold})")
    except Exception as e:  # noqa: BLE001
        msg = f"  ⚠ _save_broken 실패 — slug={slug} err={e!r}"
        if log_lines is not None:
            log_lines.append(msg)
        else:
            print(msg, file=sys.stderr, flush=True)


def _load_states(only: set[str] | None) -> list[dict]:
    out = []
    if not STATE_DIR.exists():
        return out
    for p in sorted(STATE_DIR.glob("*.json")):
        # .FAILED.json (자동 등록 실패) / .REJECTED.json (영구 거부 marker) / .BUG.json (코드 버그 마커) /
        # .BROKEN.json (health sidecar — polling 자체는 살아있음). 모두 정상 state 형식 아님 (config_path 없음) — 폴링 대상 X.
        if (p.name.endswith(".FAILED.json")
                or p.name.endswith(".REJECTED.json")
                or p.name.endswith(".BUG.json")
                or p.name.endswith(".BROKEN.json")):
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
                         db_conn, db_lock: asyncio.Lock) -> tuple[list[str], tuple, dict]:
    """한 사이트의 fetch + 결과 처리 + collected/sqlite 박기 + state 파일 쓰기까지.
    (log_lines, row, tracking) 반환 — tracking 은 호출 측 (_site_with_timeout) 이 poll_site_run_finish
    호출에 사용.

    ADR 0016 ordering — 발견한 새 글의 disk·sqlite·seen·state 박는 순서:
      ① run_dir/<slug>.new.json 쓰기 (collected 아티팩트)
      ② db_conn 으로 posts 캐시 upsert — db_lock 안에서 사이트당 1 commit (batch).
      ③ ADR 0017 persist 검증 — INSERT 후 SELECT 로 *실제 박힌* 글 카운트.
      ④ mismatch 시 missing id 를 seen 에서 제외 (CRITICAL invariant).
      ⑤ seen_post_ids = _new_seen (state.json 에 박힐 in-memory 값 갱신)
      ⑥ state.json 디스크 flush.
    crash safe: state.json 의 seen 은 sqlite 박힌 글만 인정. ②/③ 사이 crash 면 다음 폴링이 같은 글 다시 발견 → INSERT OR IGNORE 가 idempotent.

    동시 실행 가드(sem chromium/httpx) 는 호출 측 `_site_with_timeout` 에서 잡는다 — sem 대기
    시간이 P1 wall timeout 안에 포함되면 sem queue 끝의 사이트가 false timeout 됨 (2026-05-25
    1차 폴링에서 148건 발생). 분리해서 *fetch 자체* 만 wall cap.
    print 안 함 — 호출 측이 묶어서 출력해 사이트 로그 가독성 유지.
    """
    slug = st["slug"]
    strategy, adapter = _config_meta(st)
    chromium = _uses_chromium(st)
    tag = strategy + (f":{adapter}" if strategy == "handwritten" else "")
    lines: list[str] = [
        f"=== {slug} ===  {st.get('url')} [{tag or '?'}{' (chromium)' if chromium else ''}]"
        + ("  [lurking — 구독자 0]" if lurking else "")
    ]
    tr = current_trace()
    # lastmod observe (2026-05-24 A 묶음 #2) — fetch_list 와 *병렬*, observe only.
    lastmod_task = asyncio.create_task(_check_sitemap_lastmod(st))
    with tr.span("poll.site", attrs={"slug": slug, "strategy": strategy,
                                       "adapter": adapter, "chromium": chromium,
                                       "lurking": lurking}) as ssp:
        res = await _fetch_one(st, page_size=page_size,
                                max_new_articles=max_new_articles, lurking=lurking)
        ssp.set_attr("n_posts", res.get("n_posts", 0))
        ssp.set_attr("n_new", res.get("n_new", 0))
        ssp.set_attr("broken", bool(res.get("broken")))
    st["last_poll_at"] = _now_iso()
    # lastmod log — observe 결과 + fetch_list 결과 한 줄 append. fetch_list skip 결정 안 함.
    # 0.5s short drain — lastmod task 가 fetch_list 보다 늦게 끝나도 wall-clock 에 못 붙게. codex bug
    # review (2026-05-24) 의 MED 보강. 미완 시 cancel + log skip (이번 cycle 만 손실).
    try:
        obs = await asyncio.wait_for(lastmod_task, timeout=0.5)
    except asyncio.TimeoutError:
        lastmod_task.cancel()
        obs = None
    except Exception:
        obs = None
    if obs is not None:
        try:
            obs.update({"ts": st["last_poll_at"], "slug": slug,
                        "fetch_list_n_posts": res.get("n_posts", 0),
                        "fetch_list_n_new": res.get("n_new", 0),
                        "fetch_list_status": res.get("status", "")})
            SITEMAP_LASTMOD_LOG.parent.mkdir(parents=True, exist_ok=True)
            with SITEMAP_LASTMOD_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(obs, ensure_ascii=False) + "\n")
            if obs.get("current_lastmod"):
                st["sitemap_lastmod_last_seen"] = obs["current_lastmod"]
        except Exception:
            pass

    if res["broken"]:
        st["consecutive_breakage"] = int(st.get("consecutive_breakage", 0)) + 1
        st["last_status"] = res["status"]
        lines.append(f"  ⚠ 깨짐 신호 #{st['consecutive_breakage']}: {res['note']}")
        _maybe_save_broken(slug, st, note=res.get("note", ""), log_lines=lines)
        if st["consecutive_breakage"] >= settings.poll.breakage_threshold and not no_reprobe:
            # 마커 (`.BUG.json` / `.FAILED.json` / `.REJECTED.json`) 박힌 slug 은 reprobe enqueue
            # 안 함 — bug-fix / hand-config / 영구 거부 workflow 가 풀고 마커 clear 할 때까지
            # 자동 재시도 차단 (ADR 0001 "재시도 안 함" 계약). 마커 종류 별 의미:
            #   - BUG: 시스템·코드 결함 또는 reprobe N회 연속 실패 자동 stop (운영자 review).
            #   - FAILED: 자동 config 생성 실패 — hand-config 손-처리 대기.
            #   - REJECTED: 영구 거부 (게시판 아님 / policy violation 등). 사실상 polling 자체
            #     가 끊겨야 하는데 잔재 cb 가 남아 reprobe enqueue 매 cycle 발생하던 문제 봉합.
            # worker.py 의 is_blocked 가드 (L504) 가 enqueue 후 진입 시점에도 잡아주지만,
            # 매 cycle 의미 없는 rc=-7 잡 생성을 여기서 미리 차단 (52건/87 fail = 절반 이상 wasted).
            marker_path = None
            marker_kind_name = None
            for _kind in ("BUG", "FAILED", "REJECTED"):
                _p = STATE_DIR / f"{slug}.{_kind}.json"
                if _p.exists():
                    marker_path = _p
                    marker_kind_name = _kind
                    break
            if marker_path is not None:
                lines.append(
                    f"  ⏸ 연속 {st['consecutive_breakage']}회지만 {marker_kind_name} 마커 존재 — "
                    f"reprobe 스킵 (운영자 점검 대기)"
                )
                st["last_status"] = f"reprobe_skipped_{marker_kind_name.lower()}"
                res["note"] += f" | reprobe skipped ({marker_kind_name} marker)"
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
        # 정상 fetch — cb 와 BROKEN sidecar 둘 다 정리 (자가 복구 path).
        if int(st.get("consecutive_breakage", 0) or 0) > 0:
            lines.append(f"  ✓ 정상 복구 — cb {st['consecutive_breakage']} → 0 reset")
        st["consecutive_breakage"] = 0
        st["last_status"] = res["status"]  # "ok" 또는 "lurking"
        _bp = STATE_DIR / f"{slug}.BROKEN.json"
        if _bp.exists():
            try:
                _bp.unlink()
                lines.append(f"  ✓ BROKEN sidecar unlink (자가 복구)")
            except OSError as _e:
                lines.append(f"  ⚠ BROKEN unlink 실패: {_e}")
        # ADR 0016 ordering — seen 갱신은 sqlite upsert 끝난 *뒤* 에 한다. 여기선 후보값만 보관.
        new_seen_candidate = res.get("_new_seen")
        if res.get("lurking"):
            lines.append(f"  {res['n_posts']}건 / 새 글 {res['n_new']}건 (lurking — 본문 fetch·알림 생략, seen 갱신만)")
            if new_seen_candidate is not None:
                st["seen_post_ids"] = new_seen_candidate  # lurking 은 sqlite 안 박음 → 곧장 seen
        else:
            n_fetched_bodies = sum(1 for p in res["new_posts"] if (p.get("content_html") or "").strip())
            lines.append(f"  {res['n_posts']}건 / 새 글 {res['n_new']}건 (본문 fetch {n_fetched_bodies}건)")
            for p in res["new_posts"][:5]:
                lines.append(f"    NEW {p.get('post_id')}  {p.get('published_at')}  {(p.get('title') or '')[:60]}")
            # ADR 0017 persist 검증 — 새 글 INSERT 후 *실제 박힌* 글 카운트. mismatch 시 missing id 를
            # seen 에서 제외 (CRITICAL invariant — 안 박힌 글이 seen 박혀 영원히 누락되는 silent fail 차단).
            persist_data = {"n_attempted_unique": 0, "n_inserted": 0, "n_present_after": 0,
                            "missing_ids": []}
            if res["new_posts"]:
                # ① collected 디스크 (디버그 아티팩트 — 새 글 raw 스냅샷)
                (run_dir / f"{slug}.new.json").write_text(
                    json.dumps(res["new_posts"], ensure_ascii=False, indent=2), encoding="utf-8")
                # ② posts 캐시 sqlite upsert + persist 검증. db_lock 안에서 진행.
                attempted_ids = {str(post.get("post_id")) for post in res["new_posts"]}
                persist_data["n_attempted_unique"] = len(attempted_ids)
                n_inserted = 0
                async with db_lock:
                    for post in res["new_posts"]:
                        cur = db_conn.execute(
                            "INSERT OR IGNORE INTO posts(slug,post_id,title,url,published_at,category,content_html,summary,collected_at) "
                            "VALUES(?,?,?,?,?,?,?,NULL,?)",
                            (slug, str(post.get("post_id")), post.get("title"), post.get("url"),
                             post.get("published_at"), post.get("category"),
                             post.get("content_html"), _now_iso()),
                        )
                        n_inserted += cur.rowcount
                    db_conn.commit()
                    # ③ 검증 — IN clause SELECT 로 실제 박힌 id 집합.
                    placeholders = ",".join("?" for _ in attempted_ids)
                    present = {row[0] for row in db_conn.execute(
                        f"SELECT post_id FROM posts WHERE slug=? AND post_id IN ({placeholders})",
                        (slug, *attempted_ids),
                    ).fetchall()}
                persist_data["n_inserted"] = n_inserted
                persist_data["n_present_after"] = len(present)
                missing = attempted_ids - present
                if missing:
                    persist_data["missing_ids"] = sorted(missing)
                    # ④ CRITICAL invariant — missing 은 seen 에서 제외.
                    if new_seen_candidate is not None:
                        new_seen_candidate = [pid for pid in new_seen_candidate if pid not in missing]
                    st["last_status"] = "persist_mismatch"
                    lines.append(f"  ⚠ persist_mismatch — 새 글 {persist_data['n_attempted_unique']}건 중 "
                                 f"sqlite 에 {persist_data['n_present_after']}건만 박힘. "
                                 f"missing={sorted(missing)[:5]}")
            # ⑤ sqlite 다 박힘 (또는 new_posts 0건) → seen 갱신 OK
            if new_seen_candidate is not None:
                st["seen_post_ids"] = new_seen_candidate

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
    # ADR 0017 — 호출 측 (_site_with_timeout) 이 poll_site_run_finish 부르는 데 쓸 tracking dict.
    persist_data = locals().get("persist_data") or {"n_attempted_unique": 0, "n_inserted": 0,
                                                     "n_present_after": 0, "missing_ids": []}
    tracking = {
        "status": st["last_status"],
        "n_posts": int(res.get("n_posts", 0) or 0),
        "n_new": int(res.get("n_new", 0) or 0),
        "n_attempted_unique": int(persist_data.get("n_attempted_unique", 0) or 0),
        "n_inserted": int(persist_data.get("n_inserted", 0) or 0),
        "n_present_after": int(persist_data.get("n_present_after", 0) or 0),
        "note": (json.dumps({"missing_ids": persist_data["missing_ids"][:20]}, ensure_ascii=False)
                 if persist_data.get("missing_ids") else (res.get("note") or None)),
        "error_msg": None,
    }
    return lines, row, tracking


async def run(args) -> int:
    trace_attrs = {
        "sites_filter": args.sites or "(all)",
        "page_size": args.page_size,
        "max_new_articles": args.max_new_articles,
        "all_lurking_off": bool(args.all),
    }
    with start_trace("poll", attrs=trace_attrs) as tr:  # noqa: F841 (contextvar 설정용)
        return await _run_inner(args)


async def _site_with_timeout(st: dict, *, timeout: float,
                             sem_chromium: asyncio.Semaphore, sem_httpx: asyncio.Semaphore,
                             run_id: int | None, db_conn, db_lock: asyncio.Lock,
                             **kw) -> tuple[list[str], tuple, dict]:
    """ADR 0016 — 사이트별 wall timeout 래퍼. start/done/timeout/error stderr 1줄 + last_poll_duration_ms.
    ADR 0017 — happy / timeout / exception path 모두 `poll_site_run_finish` 1회 호출 (best-effort).
    ADR 0019 Phase 1 — chromium 사이트는 sem 잡은 뒤 `chromium_lock_async(slots=N)` 도 잡는다 →
    register subprocess 와 같은 N slot 공유 (RAM cap = N chromium). ordering = sem → flock →
    wait_for(_process_site). flock 획득 대기는 `settings.poll.chromium_lock_wait_budget_s`(기본
    300s) 안에 한다 — 초과 시 그 사이트만 `chromium_lock_timeout` 으로 죽고 나머지 진행. flock
    대기 시간은 wall timeout 밖 (lock_wait_ms 컬럼 분리) — register hang 해도 다른 chromium
    사이트 false timeout 안 남음.

    중요: sem(chromium/httpx) 은 wait_for **밖에서** 잡는다. 그래야 sem queue 대기 시간이 wall
    timeout 안에 포함 안 됨. 첫 구현(2026-05-25 1차) 은 sem 잡기를 _process_site 안에 두고
    wait_for 가 사이트 전체를 감싸서 sem_chromium=1 줄 끝의 148 사이트가 false timeout 됨.

    timeout 초과 시 asyncio.TimeoutError 던짐 — gather(return_exceptions=True) 가 잡아서 호출 측이
    last_status="poll_timeout" 분기 처리. duration_ms 는 모든 path 에서 박힘.
    """
    slug = st.get("slug", "?")
    started_at = _now_iso()
    t0 = time.perf_counter()
    print(f"[poll] start {slug}", file=sys.stderr, flush=True)
    # sem 결정 — strategy 보고. _process_site 가 같은 결정을 하지만 거기선 안 잡음 (분리).
    chromium = _uses_chromium(st)
    sem = sem_chromium if chromium else sem_httpx
    lock_wait_ms: int = 0  # chromium 만 박힘, httpx 는 0 → DB NULL
    if chromium:
        payload = {
            "state_path": str(st.get("_state_path") or ""),
            "slug": slug,
            "run_id": run_id,
            "page_size": kw.get("page_size"),
            "max_new_articles": kw.get("max_new_articles"),
            "lurking": bool(kw.get("lurking", False)),
            "no_reprobe": bool(kw.get("no_reprobe", False)),
            "run_dir": str(kw.get("run_dir") or ""),
        }
        # codex 2차 review LOW 5 — run_id None 시 'poll:None:slug' 가 미래 작업과 충돌
        # 안 하게 dedupe 끄고 unique INSERT.
        if run_id is not None:
            dedupe_key = f"poll:{run_id}:{slug}"
        else:
            dedupe_key = None
        async with db_lock:
            job_id, _inserted = bot_db.enqueue_job(
                db_conn,
                kind="poll_site",
                slug=slug,
                url=st.get("url"),
                dedupe_key=dedupe_key,
                sub_payload=json.dumps(payload, ensure_ascii=False),
                via="poll-cron",
                dedupe=(dedupe_key is not None),
            )
        return (
            [f"=== {slug} ===  poll_site job #{job_id} enqueued"],
            (slug, "enqueued", 0, 0, f"poll_site job #{job_id}"),
            {"status": "enqueued",
             "n_posts": 0, "n_new": 0,
             "n_attempted_unique": 0, "n_inserted": 0, "n_present_after": 0,
             "note": None, "error_msg": None},
        )

    def _finish(status: str, *, error_msg: str | None = None,
                tracking: dict | None = None, dur_ms: int | None = None) -> None:
        if dur_ms is None:
            dur_ms = int((time.perf_counter() - t0) * 1000)
        ended_at = _now_iso()
        # chromium 사이트만 lock_wait_ms 박음. httpx 는 NULL (의미 없음).
        lock_wait_db: int | None = lock_wait_ms if chromium else None
        try:
            bot_db.poll_site_run_finish(
                db_conn, run_id=run_id, slug=slug,
                started_at=started_at, ended_at=ended_at,
                status=status,
                n_posts=int((tracking or {}).get("n_posts", 0) or 0),
                n_new=int((tracking or {}).get("n_new", 0) or 0),
                n_attempted_unique=int((tracking or {}).get("n_attempted_unique", 0) or 0),
                n_inserted=int((tracking or {}).get("n_inserted", 0) or 0),
                n_present_after=int((tracking or {}).get("n_present_after", 0) or 0),
                duration_ms=dur_ms,
                lock_wait_ms=lock_wait_db,
                error_msg=error_msg or (tracking or {}).get("error_msg"),
                note=(tracking or {}).get("note"),
            )
        except Exception as e:  # noqa: BLE001
            print(f"[tracking] ⚠ _finish({slug}) failed: {e!r}", file=sys.stderr, flush=True)

    try:
        # sem 대기 — timeout 밖. sem queue 가 길어도 false timeout 안 남.
        async with sem:
            # ADR 0019 Phase 1 — chromium 사이트는 cross-process flock 도 잡는다. httpx 는 skip.
            # slots = settings.chromium_lock.slots — worker (register/reprobe) 와 같은 N 슬롯 공유
            # (capacity limit, 실 mutex 아님). RAM cap = N chromium 바이너리. ADR §2 Phase 1 원안의
            # 'slots=1 명시' 는 운영상 register 처리량 반감 비용이 커서 N100 운영값(현 slots=5) 유지.
            # flock 획득 자체는 budget(기본 300s) 안에 — N 슬롯 다 차서 못 잡으면 그 사이트만
            # chromium_lock_timeout 으로 죽고 나머지 진행.
            lock_cm = None
            if chromium:
                tr = current_trace()
                budget = float(settings.poll.chromium_lock_wait_budget_s)
                slots = int(settings.chromium_lock.slots)
                t_lock_start = time.perf_counter()
                try:
                    with tr.span("poll.chromium_flock_acquire",
                                 attrs={"slug": slug, "budget_s": budget, "slots": slots}):
                        from scripts._chromium_lock import chromium_lock_async
                        lock_cm = chromium_lock_async(timeout=budget, slots=slots)
                        await lock_cm.__aenter__()
                    lock_wait_ms = int((time.perf_counter() - t_lock_start) * 1000)
                except TimeoutError as exc:
                    lock_wait_ms = int((time.perf_counter() - t_lock_start) * 1000)
                    dur_ms = int((time.perf_counter() - t0) * 1000)
                    st["last_poll_duration_ms"] = dur_ms
                    print(f"[poll] CHROMIUM_LOCK_TIMEOUT {slug} t={dur_ms}ms "
                          f"lock_wait={lock_wait_ms}ms budget={budget}s",
                          file=sys.stderr, flush=True)
                    st["last_poll_at"] = _now_iso()
                    st["last_status"] = "chromium_lock_timeout"
                    st["consecutive_breakage"] = int(st.get("consecutive_breakage", 0)) + 1
                    _maybe_save_broken(slug, st,
                                        note=f"flock wait > {budget}s ({exc})")
                    sp = st.get("_state_path")
                    if sp:
                        try:
                            Path(sp).write_text(
                                json.dumps({k: v for k, v in st.items() if k != "_state_path"},
                                           ensure_ascii=False, indent=2),
                                encoding="utf-8")
                        except Exception:  # noqa: BLE001
                            pass
                    async with db_lock:
                        _finish("chromium_lock_timeout",
                                error_msg=f"flock wait > {budget}s ({exc})",
                                dur_ms=dur_ms)
                    return (
                        [f"=== {slug} ===  ⚠ chromium_lock_timeout "
                         f"(lock_wait={lock_wait_ms}ms, budget={budget}s)"],
                        (slug, "chromium_lock_timeout", 0, 0,
                         f"flock wait > {budget}s"),
                        {"status": "chromium_lock_timeout",
                         "n_posts": 0, "n_new": 0,
                         "n_attempted_unique": 0, "n_inserted": 0, "n_present_after": 0,
                         "note": None, "error_msg": str(exc)},
                    )
            try:
                t_fetch_start = time.perf_counter()
                try:
                    result = await asyncio.wait_for(
                        _process_site(st, db_conn=db_conn, db_lock=db_lock, **kw),
                        timeout=timeout)
                except asyncio.TimeoutError:
                    dur_ms = int((time.perf_counter() - t0) * 1000)
                    fetch_dur_ms = int((time.perf_counter() - t_fetch_start) * 1000)
                    st["last_poll_duration_ms"] = dur_ms
                    print(f"[poll] TIMEOUT {slug} t={dur_ms}ms (fetch={fetch_dur_ms}ms, "
                          f"lock_wait={lock_wait_ms}ms, cap={timeout}s)",
                          file=sys.stderr, flush=True)
                    async with db_lock:
                        _finish("poll_timeout",
                                error_msg=f"wait_for cap={timeout}s, fetch={fetch_dur_ms}ms",
                                dur_ms=dur_ms)
                    raise
            finally:
                # flock 해제는 모든 path 에서. exception 으로 빠져도 release.
                if lock_cm is not None:
                    try:
                        await lock_cm.__aexit__(None, None, None)
                    except Exception as e:  # noqa: BLE001
                        print(f"[poll] ⚠ chromium_lock release failed for {slug}: {e!r}",
                              file=sys.stderr, flush=True)
        dur_ms = int((time.perf_counter() - t0) * 1000)
        st["last_poll_duration_ms"] = dur_ms
        if chromium:
            print(f"[poll] done  {slug} t={dur_ms}ms lock_wait={lock_wait_ms}ms",
                  file=sys.stderr, flush=True)
        else:
            print(f"[poll] done  {slug} t={dur_ms}ms", file=sys.stderr, flush=True)
        lines, row, tracking = result
        async with db_lock:
            _finish(tracking["status"], tracking=tracking, dur_ms=dur_ms)
        return lines, row, tracking
    except asyncio.TimeoutError:
        raise
    except BaseException as e:  # noqa: BLE001 — Cancel 포함 다 surface
        dur_ms = int((time.perf_counter() - t0) * 1000)
        st["last_poll_duration_ms"] = dur_ms
        print(f"[poll] ERROR {slug} t={dur_ms}ms {type(e).__name__}: {e!r}", file=sys.stderr, flush=True)
        try:
            async with db_lock:
                _finish("task_exception", error_msg=f"{type(e).__name__}: {e!r}", dur_ms=dur_ms)
        except Exception:  # noqa: BLE001
            pass
        raise


async def _run_inner(args) -> int:
    states = _load_states(set(args.sites) if args.sites else None)
    if not states:
        print(f"등록된 사이트 없음 ({STATE_DIR}). 먼저 `python scripts/register.py \"<URL>\"`.")
        return 0

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = COLLECTED_DIR / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    # ADR 0006 — posts 캐시 sqlite 는 _process_site 안에서 progressive upsert.
    # ADR 0016 — single connection 을 asyncio.Lock 으로 직렬화. WAL 모드라 read 는 동시 OK,
    # writer 1 직렬은 sqlite 자체 제약. 1660 사이트 × 평균 5글 ≈ 8k write 부하는 네트워크 ≪.
    # bot.sqlite3 단일 connection — fetch fail 시 무음 폴백 X (그러면 모든 사이트가 lurking
    # 으로 분류돼 본문 fetch·sqlite 캐시 통째로 skip → 알림 유실. codex 검토 권고).
    # 못 읽으면 그냥 죽는다 — 폴링 자체가 의미 없음. 단 죽을 때 connection 누수 막음 (codex 2차).
    db_conn = bot_db.connect()
    try:
        subscribed = set(bot_db.all_slugs(db_conn))
    except BaseException:
        try:
            db_conn.close()
        except Exception:
            pass
        raise
    db_lock = asyncio.Lock()

    # 2026-05-25 사용자 결정 — 구독자 0 인 사이트(lurking) 는 fetch_list 도 안 함.
    # 기존 default 동작 = lurking 도 fetch_list (seen 갱신 + 깨짐 감지). 그게 ~1024 사이트 wall
    # 412s 의 99% 를 잡아먹음. seen 갱신·자가복구 가치 ≈ 0 (새 구독자 등록 시 register 가 게이트).
    # `--all` 또는 `--sites` 명시 시는 lurking 도 포함 — 디버그·재계산용.
    if not args.all and not args.sites:
        states_before = len(states)
        states = [st for st in states if st["slug"] in subscribed]
        skipped = states_before - len(states)
        if skipped:
            print(f"[poll] lurking skip — 구독자 0 사이트 {skipped}개 제외 (전체 {states_before} → {len(states)})")
        if not states:
            print(f"[poll] 폴링 대상 0건 — 구독 등록부터 (bot.sqlite3 의 subscriptions 비어있음).")
            db_conn.close()
            return 0

    sem_chromium = asyncio.Semaphore(args.concurrency_chromium)
    sem_httpx = asyncio.Semaphore(args.concurrency_httpx)
    timeout_s = float(args.site_timeout) if args.site_timeout else POLL_SITE_TIMEOUT_S
    # fallback handler 가 wall-timeout note 만들 때도 같은 값 — CLI override 와 일관성.
    effective_timeout = timeout_s
    print(f"[poll] 병렬 fetch — chromium sem={args.concurrency_chromium}, httpx sem={args.concurrency_httpx}, "
          f"사이트 {len(states)}개, site_timeout={timeout_s}s")

    # ADR 0017 — runs 추적. run_label = collected dir basename + pid (collision-safe).
    # git_sha = ADR 0018 의 cron×commit race 가시화 (직전 run 과 sha 비교).
    pid = os.getpid()
    run_label = f"{ts}_pid{pid}"
    git_sha = _git_head_sha()
    args_json = None
    try:
        args_json = json.dumps(sys.argv[1:], ensure_ascii=False)
    except Exception:
        pass
    run_id = bot_db.poll_run_start(
        db_conn, run_label=run_label, pid=pid, git_sha=git_sha,
        args_json=args_json, n_sites=len(states),
    )
    t_run = time.perf_counter()

    tasks = [
        asyncio.create_task(_site_with_timeout(
            st, timeout=timeout_s,
            page_size=args.page_size, max_new_articles=args.max_new_articles,
            lurking=(not args.all) and (st["slug"] not in subscribed),
            no_reprobe=args.no_reprobe, run_dir=run_dir,
            sem_chromium=sem_chromium, sem_httpx=sem_httpx,
            db_conn=db_conn, db_lock=db_lock,
            run_id=run_id,
        ))
        for st in states
    ]
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        # ADR 0017 — run 종료 마킹은 connection 닫기 *전*에. tracking helper 의 best-effort 가 finally
        # 안에서도 conn 살아있을 때 동작하게.
        pass

    rows = []
    n_timeout = 0
    # ADR 0017 — 집계 aggregator. _site_with_timeout 의 happy path 가 tracking dict 반환 →
    # 그 값으로 sum. exception path 는 dict 없음 — 사이트별 finish 는 _site_with_timeout 가 박았음.
    agg = {"n_done": 0, "n_timeout": 0, "n_error": 0,
           "n_attempted_unique": 0, "n_inserted": 0, "n_present_after": 0,
           "persist_mismatch_sites": 0}
    any_chromium_enqueued = False
    n_lurking_skipped = 0
    if not args.all and not args.sites:
        n_lurking_skipped = max(0, locals().get("skipped", 0) or 0)
    for st, res in zip(states, results):
        if isinstance(res, BaseException):
            # _process_site 본문 안에서 처리 못한 예외 또는 wall timeout. state 파일에 fallback 업데이트.
            slug = st.get("slug", "?")
            is_to = isinstance(res, asyncio.TimeoutError)
            note = f"{type(res).__name__}: {res}" if not is_to else f"poll_timeout > {int(effective_timeout)}s"
            print(f"\n=== {slug} ===")
            print(f"  ⚠ {'wall timeout' if is_to else 'task 예외'}: {note}")
            st["last_poll_at"] = _now_iso()
            st["consecutive_breakage"] = int(st.get("consecutive_breakage", 0)) + 1
            st["last_status"] = "poll_timeout" if is_to else "task_exception"
            if is_to:
                n_timeout += 1
                agg["n_timeout"] += 1
            else:
                agg["n_error"] += 1
            _maybe_save_broken(slug, st, note=note)
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
            rows.append((slug, st["last_status"], 0, 0, note))
            continue
        lines, row, tracking = res
        print()
        for line in lines:
            print(line)
        rows.append(row)
        agg["n_done"] += 1
        agg["n_attempted_unique"] += int(tracking.get("n_attempted_unique", 0) or 0)
        agg["n_inserted"] += int(tracking.get("n_inserted", 0) or 0)
        agg["n_present_after"] += int(tracking.get("n_present_after", 0) or 0)
        if tracking.get("status") == "enqueued":
            any_chromium_enqueued = True
        if tracking.get("status") == "persist_mismatch":
            agg["persist_mismatch_sites"] += 1
    if n_timeout:
        print(f"\n[poll] ⚠ wall-timeout {n_timeout}건 (>{effective_timeout}s) — 그 사이트만 죽이고 나머지 진행. journal 의 `[poll] TIMEOUT <slug>` 로 식별.")
    if agg["persist_mismatch_sites"] > 0:
        print(f"\n[poll] ⚠ persist_mismatch {agg['persist_mismatch_sites']}개 사이트 — sqlite 에 안 박힌 새 글 있음 (run_id={run_id}). dashboard /runs/poll/{run_id} 확인.",
              file=sys.stderr, flush=True)

    # ADR 0017 — run finish + connection 닫기.
    dur_ms = int((time.perf_counter() - t_run) * 1000)
    if any_chromium_enqueued:
        bot_db.poll_run_mark_enqueue_done(db_conn, run_id)
    else:
        bot_db.poll_run_finish(db_conn, run_id,
                                n_done=agg["n_done"], n_timeout=agg["n_timeout"], n_error=agg["n_error"],
                                n_lurking_skipped=n_lurking_skipped,
                                n_attempted_unique=agg["n_attempted_unique"],
                                n_inserted=agg["n_inserted"],
                                n_present_after=agg["n_present_after"],
                                persist_mismatch_sites=agg["persist_mismatch_sites"],
                                duration_ms=dur_ms)
    try:
        db_conn.close()
    except Exception:
        pass

    # 요약 (사람용 summary.txt + 기계용 poll_result.json — 디버그 아티팩트, 현재 reader 없음)
    lines = [f"[poll {ts}]", ""]
    for slug, status, npos, nnew, note in rows:
        lines.append(f"  {slug}\n      status={status}  posts={npos}  new={nnew}  {note}")
    text = "\n".join(lines) + "\n"
    (run_dir / "summary.txt").write_text(text, encoding="utf-8")
    (run_dir / "poll_result.json").write_text(
        json.dumps({"ts": ts, "polled_at": _now_iso(), "run_id": run_id,
                    "sites": [{"slug": s, "status": st, "n_posts": np, "n_new": nn}
                              for s, st, np, nn, _ in rows]},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    print("\n" + text)
    print(f"→ {run_dir}")
    return 0


def _git_head_sha() -> str | None:
    """현재 HEAD 의 short sha (ADR 0018 cron×commit race 가시화). 실패 시 None."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=str(ROOT), check=False, capture_output=True, timeout=2.0, text=True,
        )
        if r.returncode == 0:
            return r.stdout.strip() or None
    except Exception:
        pass
    return None


def main(argv) -> int:
    p = argparse.ArgumentParser(description="등록된 사이트 폴링 (새 글 감지 + 깨짐 시 재-probe)")
    # 기본값은 config.toml ([poll]) 에서. CLI args 가 그걸 한 번 더 덮음.
    p.add_argument("--sites", help="쉼표 구분 slug 목록 (기본: 전부)")
    p.add_argument("--page-size", type=int, default=settings.poll.page_size)
    p.add_argument("--max-new-articles", type=int, default=settings.poll.max_new_articles,
                   help="사이트당 폴링 1회에 본문 fetch 할 새 글 상한")
    p.add_argument("--no-reprobe", action="store_true", help="깨져도 reprobe 잡 enqueue 안 함(리포트만)")
    p.add_argument("--all", action="store_true",
                   help="구독자 0 사이트도 fetch_list + 본문 fetch + 알림. 기본은 구독자 있는 사이트만 폴링 (구독자 0 = 완전 skip — 2026-05-25 사용자 결정).")
    p.add_argument("--concurrency-httpx", type=int, default=settings.poll.concurrency_httpx,
                   help="httpx_html / httpx_json 사이트 동시 fetch 상한. 가벼우니 늘려도 메모리 부담 X")
    p.add_argument("--concurrency-chromium", type=int, default=settings.poll.concurrency_chromium,
                   help="playwright_html / ArcaLiveAdapter(handwritten) 동시 fetch 상한. chromium 1개당 RAM ~200MB+ 라 작은 박스 보호용")
    p.add_argument("--site-timeout", type=float, default=None,
                   help=f"ADR 0016 — 사이트 1개당 wall timeout(초). 미지정 시 {POLL_SITE_TIMEOUT_S}s. 이 cap 넘으면 그 사이트만 poll_timeout 죽이고 나머지 진행.")
    args = p.parse_args(argv)
    if args.sites:
        args.sites = [s.strip() for s in args.sites.split(",") if s.strip()]
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
