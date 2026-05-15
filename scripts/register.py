"""사이트 등록: URL → lite probe → preflight(글페이지 HAR re-probe + probe 신호 hint) → digest → gemini(≤max_attempts) → config 저장 + baseline state.

preflight (gemini 부르기 *전에* 1회, --no-escalate 면 생략):
  (a) probe 가 잡은 첫 글 페이지를 Playwright+HAR 로 re-probe → 본문 JSON API 후보(article_candidates.json) + 렌더된 DOM(article.html) 확보
      → 프롬프트가 이걸 '⚡ 글 본문 JSON API 후보' 블록으로 자동 첨부 (httpx 본문 대신 본문 API 를 쓰는 config / strategy=playwright_html 로 유도).
  (b) probe 신호(목록 페이지가 정적 GET 으론 안 열림 + JSON API 후보 유무)로 목록 전략 hint 를 digest.escalation_hint 에 넣어 1회차부터 제공.
  → 옛날엔 "lite gen 4번 실패 → full probe + gen 4번 → 본문 hint + gen 4번 …" 식으로 escalate 했지만(최대 16회 호출), 이제 그 정보를
     처음부터 다 주고 gen 은 max_attempts(기본 4)회만. 한 라운드 안에서 검증 피드백 재시도는 그대로(generate_config_validated).

사용:
    python scripts/register.py "https://cse.skku.edu/cse/notice.do?mode=list&srCategoryId1=1582&srSearchKey=&srSearchVal="
    python scripts/register.py "<목록URL>" --out configs/my_board.json --max-attempts 4
    python scripts/register.py "<목록URL>" --reuse-probe       # probe 산출물 있으면 재사용
    python scripts/register.py "<목록URL>" --full-probe        # lite 대신 처음부터 full probe (외부/유료 서비스까지 — 보통 불필요)
    python scripts/register.py "<목록URL>" --no-escalate       # preflight(글페이지 re-probe + hint 주입) 생략, raw lite digest 로만 생성
    python scripts/register.py "<목록URL>" --article-url "<글페이지URL>"
        # probe 가 '첫 글'을 잘못 잡는 사이트용: 실제 글 본문 페이지 URL 을 직접 지정.
        # 그 글페이지를 render+HAR 로 미리 re-probe(본문 JSON API 후보·렌더 DOM 확보)하고 digest 의 article_sample 을 그걸로 맞춘 뒤 생성한다.

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
from engine.recognizers import recognize as recognize_platform  # noqa: E402
from engine.tracing import start_trace, current_trace, env_for_child  # noqa: E402
from generate import generate_config_validated, GenerationError, default_model  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONFIGS_DIR = ROOT / "configs"
STATE_DIR = ROOT / "output" / "poll_state"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_probe(url: str, *, lite: bool) -> None:
    import os
    print(f"[register] {'lite' if lite else 'full'} probe: {url}")
    cmd = [sys.executable, str(ROOT / "scripts" / "probe.py"), url, "--no-paid", "--no-crawl4ai"]
    if lite:
        cmd.append("--lite")
    child_env = {**os.environ, **env_for_child()}
    tr = current_trace()
    with tr.span("probe_subprocess", attrs={"url": url, "lite": lite}):
        rc = subprocess.call(cmd, env=child_env)
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


def _set_first_article_url(slug: str, article_url: str) -> None:
    """list_candidates.json 의 first_article_url 을 덮어쓴다 (digest 의 article_sample.url 이 여기서 옴).
    probe 가 사이드바 메뉴 링크 등을 '첫 글'로 잘못 집은 걸 사용자가 준 진짜 글 URL 로 교정할 때."""
    p = output_dir(slug) / "list_candidates.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (json.JSONDecodeError, OSError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data["first_article_url"] = article_url
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


_ARTICLE_HINT_PREFIX = "사용자가 실제 글(본문) 페이지 URL 을 직접 지정했다"


def _article_hint_text(article_url: str, n_api: int) -> str:
    """--article-url 로 글페이지를 미리 re-probe 한 뒤 생성기에 주는 지침(첫 시도부터). 사용자가 *직접 지정한* URL 이라
    "이게 글 페이지다" 는 신뢰하되, 본문 API 후보가 진짜 본문인지는 확인하라고 한다(광고 SDK 가 후보로 새는 수 있음)."""
    api_line = (f"이 글페이지는 이미 render+HAR 로 re-probe 됐다 — article_sample.api_candidates 에 본문 JSON API 후보 {n_api}건이 있다. "
                "그중 *진짜 본문을 주는* 후보(url_id_match=true·body_looks_html=true)를 골라 article.url_template=그 후보 url(글 ID 숫자를 {post_id} 로 치환), "
                "article.fetch_kind=\"json\", article.content=[{from:\"json\", path:<그 후보의 body_field_path 그대로>}], 필요하면 그 후보 request_headers 의 X-Requested-With/Referer 를 config 최상위 headers 에 추가하라. "
                "(body_field_path 가 ['ads',...] 류이거나 url 이 ad/banner/sdk/collect/gtm 류면 광고 — 무시하고, 그러면 아래 article_sample.html 의 본문 컨테이너 selector 로.) "
                if n_api else
                "본문 JSON API 후보는 못 찾았다 — article.url_template 은 이 글 URL 의 패턴(글 ID 숫자→{post_id})으로 잡고, article.content 는 article_sample.html(이미 렌더된 DOM)에서 본문 컨테이너 selector 를 찾아 잡아라(필요하면 strategy=\"playwright_html\" + article.wait_selector). ")
    return (f"{_ARTICLE_HINT_PREFIX}: {article_url} — probe 가 자동으로 집은 '첫 글'은 무시하라(메뉴/사이드바 링크였을 수 있음). 이 URL 이 글 본문 페이지다(article_sample.html 이 그 페이지). "
            f"{api_line}"
            "또한 list 쪽: 이 글 URL 에 박힌 글 ID 가 목록 행의 어디(href/data-* 속성/JSON 필드)에 나오는지 list_html 에서 보고 list.fields.post_id 와 list.fields.url 을 그에 맞춰 잡아라.")


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

    # probe Phase 9b 가 만든 클릭 진입 HAR(traffic.article_click.har)이 있으면 거기서도 본문 API 후보를 캐서 합친다 —
    # 직접 GET 으론 다른 데로 튕기는 클라이언트 라우트나, 본문 API 가 *클릭 후에야* 호출되는 SPA 는 traffic.article.har 엔 안 잡힌다.
    # 이미 디스크에 있는 파일을 한 번 더 읽는 것뿐 — 새 브라우저/네트워크 비용 없음.
    click_har = out_dir / "traffic.article_click.har"
    if click_har.exists():
        click_article_url = article_url
        try:
            cm = json.loads((out_dir / "article_click.json").read_text(encoding="utf-8"))
            if isinstance(cm, dict) and cm.get("resolved_url"):
                click_article_url = cm["resolved_url"]      # 클릭 후 최종 URL — url_id_match 점수가 정확해짐
        except (json.JSONDecodeError, OSError):
            pass
        click_cands = traffic_article_body_candidates(click_har, click_article_url)
        seen = {c.get("url") for c in cands}
        added = [c for c in click_cands if c.get("url") not in seen]
        if added:
            print(f"[register]   + traffic.article_click.har 에서 본문 API 후보 {len(added)}건 추가")
            cands = (cands + added)[:8]

    # contract 검증 — 실패해도 _reprobe_article 흐름 중단 X (WARN 후 계속)
    try:
        from probe._contract import validate_payload as _vp, ContractError as _CE
        _vp("article_candidates.json", cands, allow_extra=False)
    except _CE as e:
        print(f"[register]   ⚠ article_candidates.json contract 위반: {e}")
    except Exception:  # noqa: BLE001
        pass
    (out_dir / "article_candidates.json").write_text(json.dumps(cands, ensure_ascii=False, indent=2), encoding="utf-8")
    for c in cands[:3]:
        print(f"[register]     본문 API 후보: {c.get('method')} {c.get('url')}  body_field_path={c.get('body_field_path')} "
              f"len={c.get('body_len')} html={c.get('body_looks_html')} url_id_match={c.get('url_id_match')}")
    print(f"[register]   본문 JSON API 후보 {len(cands)}건")
    return len(cands)


def _has_json_api_candidates(digest: dict) -> bool:
    return bool(((digest.get("list_candidates") or {}).get("traffic_json_api_candidates")))


def _list_strategy_hint(digest: dict) -> Optional[str]:
    """probe 신호로 목록 전략 hint 를 만든다 (1회차부터 digest.escalation_hint 에 들어감).

    목록 페이지가 정적 GET(httpx) 으론 200 OK 가 안 나왔으면(static_ok_preset 없음 = headless 로만 됨 — JS 렌더거나 일시 차단)
    → JSON API 후보가 있으면 "httpx_json 검토하되 그 후보가 진짜 글 목록인지 확인" hint, 없으면 "playwright_html 검토" hint.
    정적 GET 이 되면 None — gemini 가 list_html / 후보들 보고 판단하게 둔다. *어느 경우든 "후보는 휴리스틱이라 광고/위젯이 섞일 수 있으니 list_html·HAR 와 대조해 확인" 을 강조한다.*"""
    if digest.get("static_ok_preset"):
        return None
    if _has_json_api_candidates(digest):
        return (
            "목록 페이지가 정적 GET(httpx)으론 200 OK 가 안 나왔다(headless 로만 됨 — JS 렌더 가능성). list_candidates.traffic_json_api_candidates 에 목록 JSON API 후보가 있으니: "
            "**먼저 그 후보(들)가 *진짜 글 목록*을 주는지 list_html·HAR 와 대조해 확인하라** — relevance 점수 순일 뿐이라 광고 SDK·트래커·다른 위젯이 섞이는 수 있다(응답이 {ads:[...]} 류거나 url 이 ad/banner/sdk/collect/gtm 류면 무시). "
            "진짜 글 목록 API 면 strategy=\"httpx_json\" 으로 (list.url_template / list_path / success_when / fields / pagination 은 그 후보 기준 — 시스템 프롬프트 'list 키' 설명 참고). "
            "후보가 다 광고/위젯이면 → list_candidates.html_repeating_patterns 중 진짜 글 목록인 걸 list_html 에서 확인해 strategy=\"playwright_html\" + list.row_selector / list.wait_selector. 마땅한 게 없으면 억지로 만들지 말고 그렇게 적어라."
        )
    if (digest.get("list_candidates") or {}).get("html_repeating_patterns"):
        return (
            "목록 페이지가 정적 GET(httpx)으론 200 OK 가 안 나왔고(JS 렌더 가능성) 목록 JSON API 후보도 없다. "
            "list_candidates.html_repeating_patterns 중 *진짜 글 목록처럼 보이는 것*(child_count 가 크고 href_pattern_guess 가 글 상세 URL 패턴 — 네비 메뉴·푸터 링크·댓글·'관련글' 위젯 말고)을 **list_html 에서 직접 확인해** 고르고: strategy=\"playwright_html\" + list.row_selector / list.wait_selector 로 그 목록이 그려질 때까지 대기, fields 는 그 렌더된 행 기준. article.content 는 글 상세 HTML 의 본문 컨테이너 selector. "
            "마땅한 글 목록 후보가 없으면(반복 패턴이 다 메뉴/위젯) 억지로 selector 만들지 말고 그렇게 적어라(handwritten 어댑터 영역)."
        )
    return None


def _preflight(slug: str, url: Optional[str], digest: dict, *, no_escalate: bool) -> dict:
    """gemini 부르기 *전에* 한 번: 옛 escalation 의 정보 수집을 "N회 실패 후 escalate" 대신 "사전 준비"로.

      (a) probe 가 잡은 첫 글 페이지(_best_article_url)를 Playwright+HAR 로 re-probe → article_candidates.json(본문 JSON API 후보)
          + article.html(렌더 DOM) 갱신. build_user_prompt 가 이걸 '⚡ 글 본문 JSON API 후보' 블록으로 자동 첨부 → 본문 API config /
          strategy=playwright_html 로 유도. (글 본문이 정적 HTML 에 멀쩡히 있는 사이트면 후보 0건이지만, 렌더된 DOM 샘플은 더 깨끗함.)
      (b) probe 신호로 목록 전략 hint(_list_strategy_hint)를 digest.escalation_hint 에. + probe 가 잡은 첫 글 URL 의 글 ID 가
          목록 행 어디 있는지 보라는 list 필드 hint.

    --no-escalate / playwright 미설치 면 해당 단계 건너뜀. probe 가 잡은 '첫 글' URL 이 *없거나 신뢰도 낮으면*(같은 호스트도
    아님 — probe 가 외부 링크를 첫 글로 오인) re-probe 를 건너뛰고 "gemini 가 list_html 에서 직접 찾아라" hint 만 준다. 반환: (보강된) digest.
    """
    if no_escalate:
        return digest
    url = url or digest.get("url") or ""
    art = _best_article_url(digest, "")
    host = urlsplit(url).netloc or urlsplit(art or "").netloc  # 목록 URL 호스트를 모르면(--slug + diagnosis 에 url 없음 등) art 호스트를 그 기준으로
    # 같은 호스트 이상이어야 re-probe (점수: 같은 호스트 +4, 글ID 숫자 +2, view/detail 류 경로 +1).
    # 그것보다 낮으면 probe 가 외부/엉뚱한 링크를 첫 글로 집은 것 — re-probe 해봤자 잘못된 article.html 샘플로 gemini 만 오도함.
    art_ok = bool(art) and _article_url_score(art, host) >= 4
    if art_ok:
        print(f"[register] preflight: 첫 글 페이지를 render+HAR 로 re-probe → {art}")
        _set_first_article_url(slug, art)          # digest 의 article_sample.url 이 우리가 re-probe 한 URL 과 일치하도록(_best_article_url 이 first_article_url 과 다른 후보를 골랐을 수 있음)
        n_api = _reprobe_article(slug, art)        # playwright 없으면 article_candidates.json=[] 쓰고 0 반환(조용)
        # _reprobe_article 이 article.html(렌더 DOM) / article_candidates.json 을 갱신했을 수 있으니 digest 재구성.
        # (playwright 미설치라 아무것도 못 바꿨어도 결과는 동일 — 무해.)
        digest = build_digest(slug=slug, url=url)
        if n_api:
            print(f"[register]   → 본문 JSON API 후보 {n_api}건, 프롬프트에 ⚡ 블록으로 첨부됨 (단, gemini 가 진짜 본문인지 확인하게 함)")
    elif art:
        print(f"[register] preflight: probe 가 첫 글로 집은 게 다른 호스트({art}) — re-probe 건너뜀(probe 오인 가능성). gemini 가 list_html 에서 직접 찾게 둠.")
    else:
        print("[register] preflight: probe 가 첫 글 URL 을 못 찾음 — re-probe 건너뜀.")

    hints: list[str] = []
    lh = _list_strategy_hint(digest)
    if lh:
        hints.append(lh)
    if art_ok:
        hints.append(
            f"probe 가 '{art}' 를 '첫 글' 로 추정하고 그 페이지를 render+HAR 로 re-probe 했다 — article_sample.html / api_candidates / article_sample.url 이 그것. "
            "**이게 진짜 글 본문 페이지가 맞는지 article_sample.html 을 보고 먼저 판단하라** — 메뉴/카테고리/서브게시판 페이지였을 수 있다. "
            "맞으면: 이 글 URL 에 박힌 글 ID 숫자가 목록 행의 어디(href / data-* 속성 / JSON 필드)에 나오는지 list_html 에서 보고 list.fields.post_id·url 을 그에 맞춰라. "
            "아니면: list_html 의 글 목록 행에서 글 상세로 가는 href 패턴을 직접 보고 article.url_template / list.fields.url 을 잡아라(article_sample 은 부정확하니 본문 selector 는 fallback chain 2~3개로, 또는 register.py --article-url \"<진짜 글 URL>\" 로 재등록)."
        )
    elif art:
        hints.append(
            f"⚠ probe 가 '첫 글' 로 집은 게 이 사이트와 *다른 호스트*({art}) — 외부 링크를 글로 오인한 것이다. article_sample.html / article_sample.url / first_article_url 을 *글 페이지로 쓰지 마라*. "
            "list_html 의 글 목록 행에서 글 상세로 가는 href(또는 data-* / 인라인 JS) 패턴을 직접 보고 list.fields.url 과 (필요하면) article.url_template·list.fields.post_id 를 잡아라. 본문 selector 는 그렇게 잡은 글 URL 기준으로(확신 없으면 fallback chain 2~3개). "
            "확신 안 서면 멈추고 그렇게 적어라 — register.py --article-url \"<진짜 글 하나 URL>\" 로 글 URL 을 직접 주면 정확해진다."
        )
    else:
        hints.append(
            "probe 가 '첫 글' URL 을 못 찾았다(목록 행에 글 상세 링크가 안 보임 — href 가 javascript: 거나 인라인 JS 데이터거나) — article_sample 은 비어있거나 부정확하다. "
            "list_html / list_candidates.html_repeating_patterns / inline_js_data_candidates 를 보고 글 ID·글 URL 이 어디 있는지 찾아 list.fields.post_id·url 을 잡아라(샘플 article 이 없으니 article.content selector 는 글 상세를 직접 받아 정해야 할 수도). "
            "정적 CSS 만으론 안 될 것 같으면(javascript: 링크 + data-* 도 없음) 억지로 만들지 말고 handwritten 어댑터가 필요하다고 적어라."
        )
    if hints:
        digest["escalation_hint"] = "\n\n".join(hints)
    return digest


def _try_known_platform(url: str, slug: str, *, out: Optional[str], force: bool) -> Optional[int]:
    """url 이 알려진 플랫폼(engine.recognizers)이면 probe/Gemini 없이 바로 config 작성·등록.
    반환: 0=등록 성공 / None=인식 안 됨 · 잘못 인식(fetch_list 0건/예외) · 기존 config 존재(--force 없이) → 호출 측이 일반 파이프라인으로 폴백.
    (정책 검사 -- 로그인/차단 -- 는 안 함: 알려진 플랫폼은 공개 게시판이고, 비공개·등급제한이면 어댑터가 본문만 비워 반환하니 목록 등록은 그대로 됨.)
    slug 는 register.py 가 호출된 URL 기준(봇 _is_registered 가 그 slug 로 찾으므로) — config 의 _source_url 도 그 url 로 맞춤."""
    cfg = recognize_platform(url)
    if cfg is None:
        return None
    name = cfg.get("_recognized_platform", "?")
    out_path = Path(out) if out else (CONFIGS_DIR / f"{slug}.json")
    if out_path.exists() and not force:
        print(f"[register] 알려진 플랫폼({name})으로 보이지만 {out_path} 이미 존재 — 인식 경로 건너뜀(덮어쓰려면 --force, 또는 일반 파이프라인으로 진행).")
        return None
    cfg["_source_url"] = url  # 호출된 URL 로 통일 (slug 와 일치)
    from engine import validate_config, make_adapter
    try:
        validate_config(cfg)
    except Exception as e:  # noqa: BLE001
        print(f"[register] 알려진 플랫폼({name}) config 스키마 검증 실패 — 일반 파이프라인으로 폴백: {e}")
        return None
    print(f"[register] 🔎 알려진 플랫폼 인식: {name} — probe/gemini 생략, 바로 등록 시도 "
          f"(strategy={cfg.get('strategy')}{', adapter=' + cfg['adapter'] if cfg.get('adapter') else ''})")

    async def _baseline():
        async with make_adapter(cfg) as a:
            return await a.fetch_list(page=1, page_size=30)
    try:
        posts = asyncio.run(_baseline())
    except Exception as e:  # noqa: BLE001
        print(f"[register] 알려진 플랫폼({name}) fetch_list 실패 — 잘못 인식한 듯, 일반 파이프라인으로 폴백: {e!r}")
        return None
    if not posts:
        print(f"[register] 알려진 플랫폼({name})으로 인식했지만 글 0건 — 잘못 인식한 듯, 일반 파이프라인으로 폴백.")
        return None

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    post_ids = [str(pp.post_id) for pp in posts]
    sp = _save_state(slug, url, out_path, post_ids)
    print(f"[register] ✅ 등록 완료 (알려진 플랫폼: {name}) — baseline {len(post_ids)}건  config={out_path}  state={sp}")
    for pp in posts[:3]:
        print(f"    {pp.post_id}  {pp.published_at}  {(pp.title or '')[:60]}")
    return 0


def main(argv) -> int:
    # parent process (bot worker) 가 env 로 trace_id 전달 → start_trace 가 같은 trace 안에서
    # inner spans 추가. CLI 단독 호출이면 새 root trace 생성 (kind="probe").
    with start_trace("probe", attrs={"cli_argv": " ".join(argv[:6])}):
        return _main_inner(argv)


def _main_inner(argv) -> int:
    p = argparse.ArgumentParser(description="사이트 등록 (URL → config + baseline). --list 로 등록 현황 조회.")
    p.add_argument("url", nargs="?", help="목록 URL")
    p.add_argument("--slug", help="이미 probe 한 slug (url 대신; 그땐 probe 안 돌림)")
    p.add_argument("--config", help="이미 작성된 config 파일을 그대로 등록(probe/gemini 생략 — 손으로 짠 config / handwritten strategy 용). fetch_list 로 baseline 만 잡음.")
    p.add_argument("--list", action="store_true", help="등록된 사이트 현황을 표로 출력하고 종료 (output/poll_state/ + bot.sqlite3 기준)")
    p.add_argument("--csv", nargs="?", const=str(ROOT / "output" / "registered_sites.csv"),
                   help="--list 와 함께: 사이트 목록을 CSV 로도 저장 (값 생략 시 output/registered_sites.csv)")
    p.add_argument("--out", help="config 저장 경로 (기본: configs/<slug>.json)")
    p.add_argument("--max-attempts", type=int, default=4, help="gemini 생성+검증 시도 횟수 (한 라운드 안에서 검증 피드백 재시도)")
    p.add_argument("--reuse-probe", action="store_true", help="probe 산출물 있으면 재사용")
    p.add_argument("--full-probe", action="store_true", help="lite 대신 처음부터 full probe (외부 Jina/Crawl4AI·유료 서비스까지 — 보통 불필요, 느림)")
    p.add_argument("--no-escalate", action="store_true",
                   help="preflight(첫 글 페이지 render+HAR re-probe + probe 신호 기반 목록 전략 hint 주입) 생략 — raw lite digest 로만 생성 (디버깅용)")
    p.add_argument("--no-recognize", action="store_true",
                   help="알려진 플랫폼(engine.recognizers) 자동 인식을 끄고 probe→gemini 일반 파이프라인을 강제 (디버깅/검증용)")
    p.add_argument("--article-url", metavar="URL",
                   help="실제 글 본문 페이지 URL 힌트 (probe 의 '첫 글' 자동 탐지가 메뉴/사이드바 링크를 잘못 집는 사이트용). "
                        "이 URL 을 render+HAR 로 미리 re-probe 해서 본문 JSON API 후보·렌더 DOM 을 확보하고 digest 의 article_sample 을 그걸로 맞춘 뒤 생성한다.")
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
        # 알려진 플랫폼이면 probe/gemini 건너뛰고 바로 등록 (실패하면 일반 파이프라인으로 폴백)
        if not args.no_recognize:
            if (args.article_url or "").strip():
                print("[register] 알림: --article-url 은 알려진 플랫폼으로 인식되면 무시됩니다(probe 를 건너뛰므로). 인식 안 되면 아래 probe 경로에서 그대로 적용됨.")
            tr = current_trace()
            with tr.span("known_platform_try", attrs={"slug": slug, "url": url}) as sp:
                rc = _try_known_platform(url, slug, out=args.out, force=args.force)
                sp.set_attr("matched", rc is not None)
            if rc is not None:
                return rc
        out_dir = output_dir(slug)
        if not (args.reuse_probe and out_dir.exists() and (out_dir / "diagnosis.json").exists()):
            _run_probe(url, lite=not args.full_probe)

    print(f"[register] digest 구성: slug={slug}")
    tr = current_trace()
    with tr.span("build_digest", attrs={"slug": slug}):
        digest = build_digest(slug=slug, url=url)
    url = url or digest.get("url") or ""

    ok_policy, msgs = _policy_check(digest, url)
    for m in msgs:
        print(f"[register] {m}")
    if not ok_policy:
        print("[register] ❌ 등록 거부 (위 사유).")
        return 2

    # preflight: gemini 부르기 전에 정보 수집을 끝낸다 (옛 escalation 의 "N회 실패 후" 대신 "처음부터").
    #   --article-url 가 있으면 그 글 URL 로 first_article_url 교정 + re-probe + 강한 hint (probe 의 '첫 글' 휴리스틱이
    #   메뉴/사이드바 링크를 잘못 집는 사이트용); 없으면 _preflight 가 probe 가 잡은 첫 글로 re-probe + probe 신호 hint.
    article_url_hint = (args.article_url or "").strip() or None
    if article_url_hint and not article_url_hint.startswith(("http://", "https://")):
        print(f"[register] ⚠ --article-url 은 http(s):// URL 이어야 함 — 무시: {article_url_hint!r}")
        article_url_hint = None
    with current_trace().span("preflight",
                              attrs={"slug": slug,
                                     "article_url_hint": bool(article_url_hint),
                                     "no_escalate": bool(args.no_escalate)}):
        if article_url_hint:
            print(f"[register] --article-url 힌트: {article_url_hint} — first_article_url 교정 + 그 글페이지 render+HAR re-probe")
            _set_first_article_url(slug, article_url_hint)
            n_api = _reprobe_article(slug, article_url_hint)
            digest = build_digest(slug=slug, url=url)
            hint = _article_hint_text(article_url_hint, n_api)
            lh = _list_strategy_hint(digest)        # 목록이 JS-gated 면 httpx_json/playwright_html 전환 hint 도 함께
            digest["escalation_hint"] = (hint + "\n\n" + lh) if lh else hint
        else:
            digest = _preflight(slug, url, digest, no_escalate=args.no_escalate)

    out_path = Path(args.out) if args.out else (CONFIGS_DIR / f"{slug}.json")
    if out_path.exists() and not args.force:
        print(f"[register] 주의: {out_path} 이미 존재 — 덮어쓰려면 --force. 새 결과는 {out_path}.new 로 저장.")
        out_path = out_path.with_suffix(out_path.suffix + ".new")

    print(f"[register] gemini 생성+검증 (모델={args.model or default_model()}, 최대 {args.max_attempts}회):")
    gem_span_cm = current_trace().span("gemini_gen_validate",
                                        attrs={"slug": slug,
                                               "model": args.model or default_model(),
                                               "max_attempts": args.max_attempts})
    gem_span_cm.__enter__()
    _gem_closed = False
    try:
        cfg, rep = _gen(digest, max_attempts=args.max_attempts, model=args.model)
    except GenerationError as e:
        if args.no_escalate:
            _ctx = "--no-escalate: preflight(글페이지 re-probe + probe 신호 hint) 생략, raw lite digest 로 생성한 상태"
        elif digest.get("escalation_hint") or article_url_hint:
            _ctx = "preflight: 글페이지 HAR re-probe + probe 신호 hint 적용 상태"
        else:
            _ctx = "preflight 돌렸으나 글 페이지 후보 없음/추가 hint 없음 — 사실상 raw lite digest"
        fp = _save_failed(slug, url, f"gemini 생성+검증 {args.max_attempts}회 실패 ({_ctx})",
                          getattr(e, "last_config", None), getattr(e, "last_feedback", str(e)))
        print(f"\n[register] ❌ 자동 처리 불가. → {fp}")
        print("  → docs/config 자동생성 실패 케이스.md 에서 .FAILED.json 의 last_feedback([FAIL] <체크명>) 로 케이스 판별 → 보통 손작성 config(register.py --config)로 해결, 안 되면 손어댑터(docs/사이트 어댑터 추가 가이드.md).")
        print("  (probe 가 '첫 글'을 잘못 집은 게 의심되면: register.py \"<목록URL>\" --article-url \"<실제 글 하나 URL>\" 로 재시도.)")
        print(f"  마지막 실패 사유:\n{getattr(e, 'last_feedback', e)}")
        try:
            gem_span_cm.__exit__(type(e), e, e.__traceback__)
            _gem_closed = True
        except Exception:  # noqa: BLE001
            _gem_closed = True
        return 1
    finally:
        # 아직 안 닫혔으면 — 정상 종료(exc=None) 또는 GenerationError 외의 예외 — 항상 닫는다.
        if not _gem_closed:
            exc_t, exc_v, exc_tb = sys.exc_info()
            try:
                gem_span_cm.__exit__(exc_t, exc_v, exc_tb)
            except Exception:  # noqa: BLE001
                pass

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
