"""사이트 등록: URL → 경량 probe → digest → gemini(재시도 루프) → config 저장 + baseline state.

escalation (config 생성 실패 시, --no-escalate 면 전부 생략):
  1) lite probe 였으면 → full probe 로 다시 probe 후 재시도.
  2) 글 *본문* 추출 실패(article_body_len)였으면 → 글페이지를 Playwright+HAR 로 re-probe 해서
     본문 JSON API 후보(article_candidates.json)·렌더된 DOM 을 확보하고, 그걸 쓰라는 강한 hint 와 함께 재시도
     (→ httpx 본문 대신 본문 API 를 쓰는 config, 또는 strategy=playwright_html 로 자동 전환을 유도).

사용:
    python scripts/register.py "https://cse.skku.edu/cse/notice.do?mode=list&srCategoryId1=1582&srSearchKey=&srSearchVal="
    python scripts/register.py "<URL>" --out configs/my_board.json --max-attempts 4
    python scripts/register.py "<URL>" --reuse-probe          # probe 산출물 있으면 재사용
    python scripts/register.py "<URL>" --full-probe            # 처음부터 full probe
    python scripts/register.py "<URL>" --no-escalate           # 어떤 escalation 도 안 함(lite→full, 글페이지 re-probe 둘 다)

성공: configs/<slug>.json 저장 + output/poll_state/<slug>.json (baseline = 현재 글 post_id 집합).
실패: output/poll_state/<slug>.FAILED.json + "자동 처리 불가 — 손으로 config/어댑터 작성 필요" 안내.
정책: LOGIN_REQUIRED / 접근 차단 사이트는 등록 거부. robots Disallow 면 경고만 띄우고 진행.
필요: Gemini API 키 (GEMINI_API_KEYS / GEMINI_API_KEY env 또는 GEMINI_API_KEY.md 파일). 글페이지 re-probe 엔 playwright 필요.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from probe.paths import output_dir, url_to_slug  # noqa: E402
from engine.digest import build_digest  # noqa: E402
from generate import generate_config_validated, GenerationError, default_model  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONFIGS_DIR = ROOT / "configs"
STATE_DIR = ROOT / "output" / "poll_state"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_probe(url: str, *, lite: bool) -> None:
    print(f"[register] {'lite' if lite else 'full'} probe: {url}")
    cmd = [sys.executable, str(ROOT / "scripts" / "probe.py"), url, "--no-paid", "--no-crawl4ai"]
    if lite:
        cmd.append("--lite")
    rc = subprocess.call(cmd)
    if rc != 0:
        raise SystemExit(f"probe 실패 (rc={rc})")


def _entry_matrix_has_ok_list(digest: dict) -> bool:
    for r in (digest.get("entry_matrix") or []):
        if r.get("target") == "list" and r.get("classification") == "OK":
            return True
    return False


def _robots_path_matches(path: str, pattern: str) -> bool:
    """robots.txt 식 경로 매칭: 접두어 매칭 + `*` 와일드카드 + 끝의 `$` 앵커."""
    import re as _re
    p = pattern
    anchored = p.endswith("$")
    if anchored:
        p = p[:-1]
    rx = _re.escape(p).replace(r"\*", ".*")
    try:
        return _re.match("^" + rx + ("$" if anchored else ""), path) is not None
    except _re.error:
        return path.startswith(pattern.split("*", 1)[0])


def _policy_check(digest: dict, url: str) -> tuple[bool, list[str]]:
    """(등록 가능?, 메시지들). 차단/로그인이면 False. robots Disallow 면 경고만(True 유지)."""
    msgs: list[str] = []
    verdict = (digest.get("verdict") or "").lower()
    if "login" in verdict:
        return False, [f"로그인 필요 사이트 (verdict={digest.get('verdict')!r}) — 자동 등록 미지원. "
                       "로그인은 사용자가 한 번 수동으로(Playwright headful) 해야 하며 이번 단계 범위 밖."]
    if not _entry_matrix_has_ok_list(digest):
        return False, [f"목록 페이지에 정적으로도 headless 로도 접근 실패 (verdict={digest.get('verdict')!r}). "
                       "차단(BLOCKED) 사이트로 보임 — 차단 우회는 하지 않음. 등록 거부."]
    # robots Disallow — 경고만 (와일드카드 * / 끝앵커 $ 도 처리)
    path = urlsplit(url).path or "/"
    for dis in (digest.get("robots") or {}).get("disallow") or []:
        d = (dis or "").strip()
        if not d:
            continue
        if d == "/":
            msgs.append("⚠ robots.txt 가 'Disallow: /' (사이트 전체 크롤링 금지) 라고 명시. 그래도 진행은 하지만 권장하지 않음.")
            continue
        if _robots_path_matches(path, d):
            msgs.append(f"⚠ robots.txt 가 'Disallow: {d}' 라고 명시 — 이 경로({path})를 자동 접근 금지로 표시. 그래도 진행함(경고).")
    cd = (digest.get("robots") or {}).get("crawl_delay")
    if cd:
        msgs.append(f"ℹ robots.txt Crawl-Delay={cd}s — config 의 polite_sleep 에 반영(이 값 이상). 폴링/전체 스캔이 느릴 수 있음.")
    return True, msgs


def _save_state(slug: str, url: str, config_path: Path, post_ids: list[str]) -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    p = STATE_DIR / f"{slug}.json"
    p.write_text(json.dumps({
        "slug": slug,
        "url": url,
        "config_path": str(config_path),
        "registered_at": _now_iso(),
        "last_poll_at": None,
        "last_status": "registered",
        "consecutive_breakage": 0,
        "n_baseline": len(post_ids),
        "seen_post_ids": post_ids,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    # 등록과 동시에 FAILED 마커 / triage 큐 항목이 남아있으면 제거
    fp = STATE_DIR / f"{slug}.FAILED.json"
    if fp.exists():
        fp.unlink()
    _prune_triage_queue(slug)
    return p


def _prune_triage_queue(slug: str) -> None:
    """봇이 쌓는 output/triage_queue.jsonl 에서 이 slug 항목 제거 (등록되면 더 이상 triage 대상 아님)."""
    q = ROOT / "output" / "triage_queue.jsonl"
    if not q.exists():
        return
    try:
        kept: list[str] = []
        for line in q.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                kept.append(line)
                continue
            if rec.get("slug") != slug:
                kept.append(line)
        if kept:
            q.write_text("\n".join(kept) + "\n", encoding="utf-8")
        else:
            q.unlink()
    except OSError:
        pass


def _save_failed(slug: str, url: str, reason: str, last_config, last_feedback: str) -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    p = STATE_DIR / f"{slug}.FAILED.json"
    p.write_text(json.dumps({
        "slug": slug, "url": url, "failed_at": _now_iso(),
        "reason": reason, "last_config": last_config, "last_feedback": last_feedback,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _attempt_logger(i, cfg, rep, ok, msg):
    print(f"  시도 {i}: {'PASS' if ok else 'FAIL'} — {msg}")


def _list_sites(csv_path: Optional[str]) -> int:
    """등록 사이트 현황 = output/poll_state/<slug>.json (사이트당 1파일) + 구독 수(bot.sqlite3).
    레지스트리는 여기지 문서가 아님. --csv 면 그 경로(기본 output/registered_sites.csv)에도 씀."""
    sub_count: dict[str, int] = {}
    try:
        from bot import db as _db  # noqa: PLC0415
        conn = _db.connect()
        for r in conn.execute("SELECT slug, COUNT(*) FROM subscriptions GROUP BY slug").fetchall():
            sub_count[r[0]] = r[1]
        conn.close()
    except Exception:  # noqa: BLE001  bot.sqlite3 없으면 그냥 구독 0
        pass
    rows: list[dict] = []
    if STATE_DIR.exists():
        for p in sorted(STATE_DIR.glob("*.json")):
            failed = p.name.endswith(".FAILED.json")
            try:
                st = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            slug = st.get("slug") or (p.name[:-len(".FAILED.json")] if failed else p.stem)
            cfgp = st.get("config_path") or ""
            strategy = ""
            if cfgp and Path(cfgp).exists():
                try:
                    strategy = json.loads(Path(cfgp).read_text(encoding="utf-8")).get("strategy", "")
                except Exception:  # noqa: BLE001
                    pass
            rows.append({
                "slug": slug, "url": st.get("url", ""), "strategy": strategy,
                "baseline": st.get("n_baseline", ""), "last_poll": st.get("last_poll_at") or "",
                "status": ("FAILED" if failed else (st.get("last_status") or "")),
                "breakage": st.get("consecutive_breakage", 0),
                "subscribers": sub_count.get(slug, 0), "config": cfgp,
            })
    if not rows:
        print("(등록된 사이트 없음 — output/poll_state/ 비어있음)")
        return 0
    rows.sort(key=lambda r: (r["status"] == "FAILED", r["slug"]))
    w_slug = max(len("slug"), max(len(r["slug"]) for r in rows))
    w_strat = max(len("strategy"), max(len(str(r["strategy"])) for r in rows))
    print(f"{'slug':<{w_slug}}  {'strategy':<{w_strat}}  {'base':>5}  {'subs':>4}  {'status':<10}  url")
    for r in rows:
        print(f"{r['slug']:<{w_slug}}  {str(r['strategy']):<{w_strat}}  {str(r['baseline']):>5}  "
              f"{str(r['subscribers']):>4}  {str(r['status']):<10}  {r['url']}")
    print(f"\n총 {len(rows)}건 (FAILED 포함). 레지스트리: {STATE_DIR}/  ·  구독: output/bot.sqlite3")
    if csv_path:
        import csv as _csv  # noqa: PLC0415
        cp = Path(csv_path)
        cp.parent.mkdir(parents=True, exist_ok=True)
        with cp.open("w", newline="", encoding="utf-8") as f:
            wr = _csv.DictWriter(f, fieldnames=["slug", "url", "strategy", "baseline", "last_poll",
                                                "status", "breakage", "subscribers", "config"])
            wr.writeheader()
            for r in rows:
                wr.writerow(r)
        print(f"→ CSV: {cp}")
    return 0


async def _generate(digest: dict, *, max_attempts: int, model):
    return await generate_config_validated(
        digest, model=model, max_attempts=max_attempts, fetch_articles=1, on_attempt=_attempt_logger,
    )


def _gen(digest: dict, *, max_attempts: int, model):
    """동기 래퍼 (asyncio.run)."""
    return asyncio.run(_generate(digest, max_attempts=max_attempts, model=model))


def _article_url_score(u: Optional[str], host: str) -> int:
    if not u or not u.startswith("http"):
        return -1
    sp = urlsplit(u)
    s = 0
    if host and sp.netloc == host:
        s += 4
    if re.search(r"\d{3,}", (sp.path or "") + "?" + (sp.query or "")):
        s += 2
    if re.search(r"(view|detail|article|notice|read|thread|post|bbs|board)", (sp.path or "").lower()):
        s += 1
    return s


def _best_article_url(digest: dict, last_fb: str) -> Optional[str]:
    """글페이지 re-probe 에 쓸 *진짜 글* URL 을 고른다. 후보:
    (1) 직전 attempt 가 실제로 추출한 글 URL (검증 피드백 텍스트의 url='...'), (2) digest 의 article_sample.url /
    list_candidates.first_article_url / html_repeating_patterns[].sample_url. — 목록과 같은 호스트 + 글ID 같은 숫자 있는 걸 우선
    (probe 가 헤더의 myinfo/login 링크를 first_article_url 로 잘못 집는 경우를 회피)."""
    host = urlsplit(digest.get("url") or "").netloc
    cands: list[str] = list(re.findall(r"url=['\"](https?://[^'\"]+)['\"]", last_fb or ""))
    lc = digest.get("list_candidates") or {}
    a = (digest.get("article_sample") or {}).get("url")
    if a:
        cands.append(a)
    if lc.get("first_article_url"):
        cands.append(lc["first_article_url"])
    for c in (lc.get("html_repeating_patterns") or []):
        if c.get("sample_url"):
            cands.append(c["sample_url"])
    cands = [u for u in cands if u and u.startswith("http")]
    if not cands:
        return None
    return max(cands, key=lambda u: _article_url_score(u, host))


def _reprobe_article(slug: str, article_url: str) -> int:
    """글 본문 페이지를 Playwright(+HAR)로 다시 받아 → article.html(렌더 DOM, digest 가 자동으로 더 큰 걸 씀) +
    article_candidates.json(본문 JSON API 후보) 갱신. 발견한 본문 API 후보 개수 반환."""
    out_dir = output_dir(slug)
    try:
        from probe.fetch_headless import fetch_with_capture, is_available
        from probe.extract import traffic_article_body_candidates
    except Exception as e:  # noqa: BLE001
        print(f"[register]   글페이지 re-probe 모듈 import 실패: {e!r}")
        (out_dir / "article_candidates.json").write_text("[]", encoding="utf-8")
        return 0
    if not is_available():
        print("[register]   playwright 미설치 — 글페이지 render+HAR re-probe 불가 (FAILED 로 떨어질 수 있음)")
        (out_dir / "article_candidates.json").write_text("[]", encoding="utf-8")
        return 0
    r = fetch_with_capture(url=article_url, out_dir=out_dir, target="article", headless=True)
    print(f"[register]   article re-probe: status={r.status} {r.classification.value}  body={r.body_path}")
    har = out_dir / "traffic.article.har"
    if not har.exists():
        har = out_dir / "traffic.har"
    cands = traffic_article_body_candidates(har, article_url) if har.exists() else []
    (out_dir / "article_candidates.json").write_text(json.dumps(cands, ensure_ascii=False, indent=2), encoding="utf-8")
    for c in cands[:3]:
        print(f"[register]     본문 API 후보: {c.get('method')} {c.get('url')}  body_field_path={c.get('body_field_path')} "
              f"len={c.get('body_len')} html={c.get('body_looks_html')} url_id_match={c.get('url_id_match')}")
    print(f"[register]   본문 JSON API 후보 {len(cands)}건")
    return len(cands)


def _has_json_api_candidates(digest: dict) -> bool:
    return bool(((digest.get("list_candidates") or {}).get("traffic_json_api_candidates")))


def _generate_with_escalation(slug: str, url: Optional[str], digest: dict, *,
                              max_attempts: int, model, no_escalate: bool, started_full: bool):
    """generate → 실패 시 escalate. 성공 (cfg, rep) 반환. 전부 실패 시 GenerationError(.last_config/.last_feedback) raise.

    escalation 단계:
      (1) lite→full probe — *목록 추출 실패가 아닐 때만*. lite 도 headless+HAR+list_candidates+replay+글페이지 probe 는
          이미 다 돈다. full 이 추가로 주는 건 외부(Jina/Crawl4AI)·유료프록시 결과뿐이라 목록 selector/목록 JSON API 발견엔
          도움이 안 된다 → `[FAIL] posts_nonempty`/`[FAIL] fetch_list` 면 full probe 재시도는 시간 낭비라 건너뛰고 (2)로.
      (2) 목록 추출 실패(`posts_nonempty`/`fetch_list`) — 추가 probe 없이 hint 만 강하게 줘서 재시도:
          json API 후보가 있으면 httpx_json 으로, 없으면 playwright_html(+wait_selector) 로 전환 유도.
      (3) 본문 추출 실패(`article_body_len`) — 글페이지를 render+HAR 로 re-probe(본문 JSON API 후보/렌더 DOM 확보) 후 hint 로 재시도.
    """
    used_full = started_full
    last_cfg = None
    last_fb = ""
    try:
        return _gen(digest, max_attempts=max_attempts, model=model)
    except GenerationError as e:
        last_cfg, last_fb = getattr(e, "last_config", None), getattr(e, "last_feedback", str(e))

    def _list_failed(fb: str) -> bool:
        return ("[FAIL] posts_nonempty" in (fb or "")) or ("[FAIL] fetch_list" in (fb or ""))

    # (1) lite → full probe — 목록 추출 실패면 건너뜀(full 은 목록 관련 정보를 더 안 줌)
    if (not no_escalate) and url and (not used_full):
        if _list_failed(last_fb):
            print("[register] 목록 추출 실패 → lite→full probe 는 건너뜀(full 이 목록 관련 정보를 추가로 안 줌) → (2) hint 재시도로.")
        else:
            print("[register] lite digest 로 실패 → full probe 로 escalate 재시도 ...")
            _run_probe(url, lite=False)
            digest = build_digest(slug=slug, url=url)
            used_full = True
            try:
                return _gen(digest, max_attempts=max_attempts, model=model)
            except GenerationError as e2:
                last_cfg, last_fb = getattr(e2, "last_config", last_cfg), getattr(e2, "last_feedback", str(e2))

    # (2) 목록 추출 실패 → 추가 probe 없이 강한 hint 로 재시도 (httpx_json 또는 playwright_html 로 전환 유도)
    if (not no_escalate) and _list_failed(last_fb):
        if _has_json_api_candidates(digest):
            print("[register] 목록 추출 실패 + JSON API 후보 있음 → httpx_json 전환 hint 로 재시도 ...")
            digest["escalation_hint"] = (
                "이전 시도들이 목록을 0건으로 추출했다 — 정적 HTML 에 글 목록 행이 없다(JS 렌더). "
                "digest 의 list_candidates.traffic_json_api_candidates 에 목록 JSON API 후보가 있다. "
                "strategy 를 \"httpx_json\" 으로 바꿔라: list.url_template = 그 후보의 url, "
                "list.list_path = 그 후보 list_hits[].path 를 키 리스트로(예 \"content.feeds\" → [\"content\",\"feeds\"]), "
                "success_when = 응답 최상위 code/result 류 필드로(예 {path:[\"code\"],equals:200}), "
                "fields 의 from:\"json\" path 는 *배열 원소* 기준으로 잡아라(원소가 {feed:{title,feedId,…}, user:{nickname}, feedLink:{pc}, board:{boardName}, …} 처럼 엔벨로프면 [\"feed\",\"title\"]·[\"user\",\"nickname\"]·[\"feedLink\",\"pc\"] 처럼 형제 객체를 가로질러 — list_hits[].item_subpath 가 있어도 item_path 로 쓰지 말고 path 를 길게 잡는 게 안전). "
                "pagination 은 그 후보 url 의 page/offset/limit 쿼리 파라미터로. "
                "본문(article)은 article_sample.api_candidates 가 있으면 그걸로(fetch_kind:\"json\"), 없으면 글 상세 URL 을 그대로 fetch_kind:\"html\" 로.")
        else:
            print("[register] 목록 추출 실패 + JSON API 후보 없음 → playwright_html 전환 hint 로 재시도 ...")
            digest["escalation_hint"] = (
                "이전 시도들이 목록을 0건으로 추출했다 — 정적 HTML 에 글 목록 행이 없고(JS 렌더) 목록 JSON API 후보도 없다. "
                "strategy 를 \"playwright_html\" 로 바꿔라: list.row_selector 와 list.wait_selector 에 "
                "list_candidates.html_repeating_patterns 중 *글 목록처럼 보이는 것*(child_count 가 크고 href_pattern_guess 가 글 상세 URL 패턴인 항목)의 selector 를 넣어 목록이 그려질 때까지 기다리게 하고, "
                "fields 는 그 렌더된 행 기준으로 잡아라. article.content 는 글 상세 페이지 HTML 에서 본문 컨테이너 selector 로(필요하면 article.wait_selector 도).")
        try:
            return _gen(digest, max_attempts=max_attempts, model=model)
        except GenerationError as e2b:
            last_cfg, last_fb = getattr(e2b, "last_config", last_cfg), getattr(e2b, "last_feedback", str(e2b))
        digest.pop("escalation_hint", None)

    # (3) 본문 추출 실패 → 글페이지 render+HAR re-probe → 강한 hint 로 재시도
    # feedback_text() 가 하드 실패를 "  [FAIL] <check>: ..." 로 찍으므로 그 정확한 마커로만 매칭(LLM 텍스트 오탐 방지)
    article_url = _best_article_url(digest, last_fb or "")
    list_was_ok = ("[FAIL] posts_nonempty" not in (last_fb or "")) and ("[FAIL] fetch_list" not in (last_fb or ""))
    if (not no_escalate) and article_url and ("[FAIL] article_body_len" in (last_fb or "")):
        print(f"[register] 글 본문 추출 실패 — 글페이지를 렌더링+트래픽 캡처로 re-probe 후 재시도: {article_url}")
        n_api = _reprobe_article(slug, article_url)
        digest = build_digest(slug=slug, url=url)
        keep_list = ("**중요: 목록(list.row_selector / list.fields / list.pagination)은 이미 검증을 통과했다(글 추출 성공) — 절대 바꾸지 마라. article 부분만 고쳐라.**\n"
                     if list_was_ok else "")
        if n_api:
            digest["escalation_hint"] = (
                "이전 시도들이 글 본문을 못 얻었다(정적 HTML 의 본문이 비었거나 100자 미만 — SPA 추정).\n" + keep_list +
                f"digest 의 article_sample.api_candidates 에 본문 JSON API 후보 {n_api}건이 있다. "
                "그중 url_id_match=true·body_looks_html=true 인 걸 골라서: list / strategy 는 그대로 두고, "
                "article.url_template = 그 후보의 url(거기 박힌 글 ID 숫자를 {post_id} 로 치환), article.fetch_kind = \"json\", "
                "article.content = [{from:\"json\", path:<그 후보의 body_field_path 그대로>}], 필요하면 그 후보의 "
                "request_headers 중 X-Requested-With / Referer 를 config 최상위 headers 에 추가하라.")
        else:
            digest["escalation_hint"] = (
                "이전 시도들이 글 본문을 못 얻었다(정적 HTML 의 본문이 비었거나 100자 미만 — SPA 추정). 본문을 주는 JSON API 후보도 못 찾았다.\n" + keep_list +
                "strategy 를 \"playwright_html\" 로 바꿔라. " + ("list.row_selector / list.fields 는 그대로 두고, " if list_was_ok else "") +
                "list.wait_selector 에 row_selector 가 가리키는 목록 행 요소의 selector 를 넣어 목록 렌더를 기다리게 하고, "
                "article.content 는 위 '글(본문) 페이지 HTML 샘플'(이제 렌더된 DOM)에서 본문 컨테이너 selector 를 찾아 새로 잡고, "
                "article.wait_selector 에 그 본문 컨테이너 selector 를 넣어 본문 렌더를 기다리게 하라.")
        try:
            return _gen(digest, max_attempts=max_attempts, model=model)
        except GenerationError as e3:
            last_cfg, last_fb = getattr(e3, "last_config", last_cfg), getattr(e3, "last_feedback", str(e3))

    err = GenerationError(f"자동 config 생성 실패 (escalation 포함). 마지막 피드백:\n{last_fb}")
    err.last_config = last_cfg  # type: ignore[attr-defined]
    err.last_feedback = last_fb  # type: ignore[attr-defined]
    raise err


def main(argv) -> int:
    p = argparse.ArgumentParser(description="사이트 등록 (URL → config + baseline). --list 로 등록 현황 조회.")
    p.add_argument("url", nargs="?", help="목록 URL")
    p.add_argument("--slug", help="이미 probe 한 slug (url 대신; 그땐 probe 안 돌림)")
    p.add_argument("--config", help="이미 작성된 config 파일을 그대로 등록(probe/gemini 생략 — 손으로 짠 config / handwritten strategy 용). fetch_list 로 baseline 만 잡음.")
    p.add_argument("--list", action="store_true", help="등록된 사이트 현황을 표로 출력하고 종료 (output/poll_state/ + bot.sqlite3 기준)")
    p.add_argument("--csv", nargs="?", const=str(ROOT / "output" / "registered_sites.csv"),
                   help="--list 와 함께: 사이트 목록을 CSV 로도 저장 (값 생략 시 output/registered_sites.csv)")
    p.add_argument("--out", help="config 저장 경로 (기본: configs/<slug>.json)")
    p.add_argument("--max-attempts", type=int, default=4, help="gemini 재시도 횟수")
    p.add_argument("--reuse-probe", action="store_true", help="probe 산출물 있으면 재사용")
    p.add_argument("--full-probe", action="store_true", help="처음부터 full probe (lite 대신)")
    p.add_argument("--no-escalate", action="store_true", help="lite 로 실패해도 full probe 로 escalate 안 함")
    p.add_argument("--model", help="Gemini 모델 (기본 GEMINI_MODEL env 또는 gemini-2.5-flash)")
    p.add_argument("--force", action="store_true", help="기존 config 가 있어도 덮어씀")
    args = p.parse_args(argv)

    if args.list:
        return _list_sites(args.csv)

    if not args.url and not args.slug and not args.config:
        p.error("url / --slug / --config / --list 중 하나 필요")

    # --- --config 모드: 이미 작성된 config 를 그대로 등록 (probe/gemini 생략) ---
    if args.config:
        from engine import load_config, validate_config, make_adapter
        cfg_path = Path(args.config)
        cfg = load_config(cfg_path)
        validate_config(cfg)
        stem = cfg_path.stem
        print(f"[register --config] {cfg_path}  strategy={cfg.get('strategy')}  site={cfg.get('site')}  board={cfg.get('board')}")

        async def _baseline():
            async with make_adapter(cfg) as a:
                return await a.fetch_list(page=1, page_size=30)
        posts = asyncio.run(_baseline())
        post_ids = [str(p.post_id) for p in posts]
        url0 = cfg.get("_source_url") or ((cfg.get("list") or {}).get("url_template") or "").format(board=cfg.get("board", ""))
        # _save_state 가 같은 slug 의 .FAILED.json 마커도 치워 줌 (안 그러면 봇 _is_registered 가 계속 False).
        sp = _save_state(stem, url0, cfg_path, post_ids)
        print(f"[register --config] ✅ 등록 완료 — baseline {len(post_ids)}건, state={sp}")
        for p in posts[:3]:
            print(f"    {p.post_id}  {p.published_at}  {(p.title or '')[:60]}")
        return 0

    if args.slug:
        slug = args.slug
        url = None
    else:
        url = args.url
        slug = url_to_slug(url)
        out_dir = output_dir(slug)
        if not (args.reuse_probe and out_dir.exists() and (out_dir / "diagnosis.json").exists()):
            _run_probe(url, lite=not args.full_probe)

    print(f"[register] digest 구성: slug={slug}")
    digest = build_digest(slug=slug, url=url)
    url = url or digest.get("url") or ""

    ok_policy, msgs = _policy_check(digest, url)
    for m in msgs:
        print(f"[register] {m}")
    if not ok_policy:
        print("[register] ❌ 등록 거부 (위 사유).")
        return 2

    out_path = Path(args.out) if args.out else (CONFIGS_DIR / f"{slug}.json")
    if out_path.exists() and not args.force:
        print(f"[register] 주의: {out_path} 이미 존재 — 덮어쓰려면 --force. 새 결과는 {out_path}.new 로 저장.")
        out_path = out_path.with_suffix(out_path.suffix + ".new")

    print(f"[register] gemini 생성+검증 (모델={args.model or default_model()}, 최대 {args.max_attempts}회):")
    try:
        cfg, rep = _generate_with_escalation(
            slug, url, digest,
            max_attempts=args.max_attempts, model=args.model,
            no_escalate=args.no_escalate, started_full=args.full_probe,
        )
    except GenerationError as e:
        fp = _save_failed(slug, url, "gemini 생성+검증 실패 (lite→full→글페이지 re-probe 등 escalation 모두 소진)",
                          getattr(e, "last_config", None), getattr(e, "last_feedback", str(e)))
        print(f"\n[register] ❌ 자동 처리 불가. → {fp}")
        print("  → docs/config 자동생성 실패 케이스.md 에서 .FAILED.json 의 last_feedback([FAIL] <체크명>) 로 케이스 판별 → 보통 손작성 config(register.py --config)로 해결, 안 되면 손어댑터(docs/사이트 어댑터 추가 가이드.md).")
        print(f"  마지막 실패 사유:\n{getattr(e, 'last_feedback', e)}")
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state_path = _save_state(slug, url, out_path, rep.all_post_ids)

    print(f"\n[register] ✅ 등록 완료")
    print(f"  config: {out_path}  (strategy={cfg.get('strategy')}, site={cfg.get('site')}, board={cfg.get('board')})")
    print(f"  state : {state_path}  (baseline {len(rep.all_post_ids)}건 — 이 글들은 '새 글' 아님)")
    if rep.soft_failures():
        print(f"  경고: " + "; ".join(f"{c.name}({c.detail})" for c in rep.soft_failures()))
    for sp in rep.sample_posts[:3]:
        print(f"    {sp.get('post_id')}  {sp.get('published_at')}  {(sp.get('title') or '')[:60]}")
    print(f"  → 폴링: python scripts/poll.py   (M6 에서 구현)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
