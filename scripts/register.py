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
    # 등록과 동시에 FAILED 마커가 남아있으면 제거
    fp = STATE_DIR / f"{slug}.FAILED.json"
    if fp.exists():
        fp.unlink()
    return p


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


async def _generate(digest: dict, *, max_attempts: int, model):
    return await generate_config_validated(
        digest, model=model, max_attempts=max_attempts, fetch_articles=1, on_attempt=_attempt_logger,
    )


def _gen(digest: dict, *, max_attempts: int, model):
    """동기 래퍼 (asyncio.run)."""
    return asyncio.run(_generate(digest, max_attempts=max_attempts, model=model))


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


def _generate_with_escalation(slug: str, url: Optional[str], digest: dict, *,
                              max_attempts: int, model, no_escalate: bool, started_full: bool):
    """generate → 실패 시 escalate: (1) lite probe 였으면 full probe 로 재시도, (2) 본문 추출 실패였으면
    글페이지를 render+HAR 로 re-probe(본문 JSON API 후보/렌더 DOM 확보) 후 강한 hint 와 함께 재시도.
    성공 (cfg, rep) 반환. 전부 실패 시 GenerationError(.last_config/.last_feedback) raise."""
    used_full = started_full
    last_cfg = None
    last_fb = ""
    try:
        return _gen(digest, max_attempts=max_attempts, model=model)
    except GenerationError as e:
        last_cfg, last_fb = getattr(e, "last_config", None), getattr(e, "last_feedback", str(e))

    # (1) lite → full probe
    if (not no_escalate) and url and (not used_full):
        print("[register] lite digest 로 실패 → full probe 로 escalate 재시도 ...")
        _run_probe(url, lite=False)
        digest = build_digest(slug=slug, url=url)
        used_full = True
        try:
            return _gen(digest, max_attempts=max_attempts, model=model)
        except GenerationError as e2:
            last_cfg, last_fb = getattr(e2, "last_config", last_cfg), getattr(e2, "last_feedback", str(e2))

    # (2) 본문 추출 실패 → 글페이지 render+HAR re-probe → 강한 hint 로 재시도
    article_url = ((digest.get("article_sample") or {}).get("url")
                   or (digest.get("list_candidates") or {}).get("first_article_url"))
    # feedback_text() 가 하드 실패를 "  [FAIL] <check>: ..." 로 찍으므로 그 정확한 마커로만 매칭(LLM 텍스트 오탐 방지)
    if (not no_escalate) and article_url and ("[FAIL] article_body_len" in (last_fb or "")):
        print(f"[register] 글 본문 추출 실패 — 글페이지를 렌더링+트래픽 캡처로 re-probe 후 재시도: {article_url}")
        n_api = _reprobe_article(slug, article_url)
        digest = build_digest(slug=slug, url=url)
        if n_api:
            digest["escalation_hint"] = (
                "이전 시도들이 글 본문을 못 얻었다(정적 HTML 의 본문이 비었거나 100자 미만 — SPA 추정). "
                f"digest 의 article_sample.api_candidates 에 본문 JSON API 후보 {n_api}건이 있다. "
                "그중 url_id_match=true·body_looks_html=true 인 걸 골라서: list/strategy 는 그대로 두고, "
                "article.url_template = 그 후보의 url(거기 박힌 글 ID 숫자를 {post_id} 로 치환), article.fetch_kind = \"json\", "
                "article.content = [{from:\"json\", path:<그 후보의 body_field_path 그대로>}]. "
                "필요하면 그 후보의 request_headers 중 X-Requested-With / Referer 를 config 최상위 headers 에 추가하라.")
        else:
            digest["escalation_hint"] = (
                "이전 시도들이 글 본문을 못 얻었다(정적 HTML 의 본문이 비었거나 100자 미만 — SPA 추정). 본문을 주는 JSON API 후보도 못 찾았다. "
                "strategy 를 \"playwright_html\" 로 바꿔라(목록·본문 둘 다 브라우저로 렌더). "
                "위 '글(본문) 페이지 HTML 샘플' 은 이제 렌더된 DOM 이니 거기서 본문 컨테이너 CSS selector 를 찾아 article.content 에 쓰고, "
                "article.wait_selector(없으면 list.wait_selector)에 그 컨테이너(또는 목록 행) selector 를 넣어 렌더 완료를 기다리게 하라.")
        try:
            return _gen(digest, max_attempts=max_attempts, model=model)
        except GenerationError as e3:
            last_cfg, last_fb = getattr(e3, "last_config", last_cfg), getattr(e3, "last_feedback", str(e3))

    err = GenerationError(f"자동 config 생성 실패 (escalation 포함). 마지막 피드백:\n{last_fb}")
    err.last_config = last_cfg  # type: ignore[attr-defined]
    err.last_feedback = last_fb  # type: ignore[attr-defined]
    raise err


def main(argv) -> int:
    p = argparse.ArgumentParser(description="사이트 등록 (URL → config + baseline)")
    p.add_argument("url", nargs="?", help="목록 URL")
    p.add_argument("--slug", help="이미 probe 한 slug (url 대신; 그땐 probe 안 돌림)")
    p.add_argument("--config", help="이미 작성된 config 파일을 그대로 등록(probe/gemini 생략 — 손으로 짠 config / handwritten strategy 용). fetch_list 로 baseline 만 잡음.")
    p.add_argument("--out", help="config 저장 경로 (기본: configs/<slug>.json)")
    p.add_argument("--max-attempts", type=int, default=4, help="gemini 재시도 횟수")
    p.add_argument("--reuse-probe", action="store_true", help="probe 산출물 있으면 재사용")
    p.add_argument("--full-probe", action="store_true", help="처음부터 full probe (lite 대신)")
    p.add_argument("--no-escalate", action="store_true", help="lite 로 실패해도 full probe 로 escalate 안 함")
    p.add_argument("--model", help="Gemini 모델 (기본 GEMINI_MODEL env 또는 gemini-2.5-flash)")
    p.add_argument("--force", action="store_true", help="기존 config 가 있어도 덮어씀")
    args = p.parse_args(argv)
    if not args.url and not args.slug and not args.config:
        p.error("url / --slug / --config 중 하나 필요")

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
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        sp = STATE_DIR / f"{stem}.json"
        sp.write_text(json.dumps({
            "slug": stem, "url": url0, "config_path": str(cfg_path),
            "registered_at": _now_iso(), "last_poll_at": None, "last_status": "registered",
            "consecutive_breakage": 0, "n_baseline": len(post_ids), "seen_post_ids": post_ids,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
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
        print("  손으로 config/어댑터를 작성해야 함. 가이드: docs/사이트 어댑터 추가 가이드.md")
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
