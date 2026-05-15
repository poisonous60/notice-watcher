"""사이트 정찰 도구 CLI.

사용:
    python scripts/probe.py "<URL>"
"""
from __future__ import annotations

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가 (scripts/에서 패키지 import 가능하게)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from probe.baseline import baseline_check, is_baseline_blocked
from probe.diagnose import diagnose
from probe.environment import capture as capture_environment, gdpi_advice
from probe.discover import discover_feeds, read_robots
from probe.extract import (
    html_repeating_patterns,
    pick_first_article_url,
    traffic_api_candidates,
    write_list_candidates,
)
from probe.external import try_crawl4ai, try_firecrawl, try_jina
from probe.fetch_headful import (
    cookies_from_state,
    ensure_login_and_fetch,
    is_available as headful_available,
)
from probe.fetch_headless import (
    fetch_article_by_click,
    fetch_with_capture,
    is_available as headless_available,
    load_captured_headers,
)
from probe.fetch_static import fetch as fetch_static
from probe.headers import all_presets, merge_captured
from probe.hydration import extract_hydration, extract_inline_data, find_list_in_json
from probe.paid import PaidKeys, try_all_paid
from probe.paths import OUTPUT_ROOT, PROJECT_ROOT, output_dir, state_file, url_to_slug
from probe.polite import polite_sleep
from probe.replay import replay_all
from probe.report import write_summary
from probe.types import Classification, Result


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Site reconnaissance probe.")
    p.add_argument("url", help="목록 URL 하나")
    p.add_argument("--lite", action="store_true",
                   help="경량 모드: baseline + 정적 헤더(H2~H4) + headless(설치 시 항상) + Hcap + discover + extract + replay + article. "
                        "외부(Jina/Firecrawl/Crawl4AI)·유료·login 만 스킵. config 자동생성용 digest 소스.")
    p.add_argument("--no-login", action="store_true", help="LOGIN_REQUIRED 시 자동 헤드풀 띄우지 않음")
    p.add_argument("--login", action="store_true", help="분류 결과와 무관하게 헤드풀 로그인 흐름을 강제로 시도 (사용자 로그인 후 같은 URL 재진입)")
    p.add_argument("--no-headless", action="store_true", help="Phase 2 headless 비활성화 (Playwright 자체 비활성)")
    p.add_argument("--no-article-click", action="store_true",
                   help="Phase 9b(목록에서 글 링크 클릭 → 최종 페이지 캡처) 생략. 클라이언트 라우트/href=javascript: 목록 진단에 쓰임.")
    p.add_argument("--headful-debug", action="store_true", help="Phase 2를 headful로 (디버깅)")
    p.add_argument("--extra-header", action="append", default=[], help='K=V 형식, 여러 번 가능')
    p.add_argument("--no-crawl4ai", action="store_true")
    p.add_argument("--firecrawl", action="store_true", help="Firecrawl 시도(키 자동 검색)")
    p.add_argument("--no-paid", action="store_true")
    p.add_argument("--no-replay", action="store_true")
    p.add_argument("--scraperapi-key")
    p.add_argument("--scrapingbee-key")
    p.add_argument("--zyte-key")
    p.add_argument("--brightdata-proxy")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    url: str = args.url
    slug = url_to_slug(url)
    out_dir = output_dir(slug)
    print(f"[probe] URL = {url}")
    print(f"[probe] slug = {slug}")
    print(f"[probe] output = {out_dir}")
    if args.lite:
        print("[probe] LITE mode — 외부(Jina/Firecrawl/Crawl4AI)·유료·login 만 스킵 (headless/replay 는 수행)")
    print()

    def _polite() -> None:
        # lite 정찰은 한 사이트 5~6번 두드리고 끝 — 봇탐지 회피 의미 약하니 sleep 짧게.
        if args.lite:
            polite_sleep(0.2, 0.4)
        else:
            polite_sleep(1.0, 2.0)

    env = capture_environment(out_dir)
    print(f"[env] platform={env['platform']}  outbound_ip_local={env['outbound_ip_local']}")
    print(f"[env] GoodbyeDPI: running={env['goodbyedpi_running']} ({env['goodbyedpi_info']})\n")

    all_results: list[Result] = []

    # ---- Phase 0: baseline ----
    print("[Phase 0] baseline ping ...")
    baseline = baseline_check(url)
    blocked = is_baseline_blocked(baseline)
    for r in baseline.values():
        print(f"  {r.strategy} {r.url} → {r.status} {r.classification.value}")

    # ---- Phase 1: static GET with header presets ----
    presets = all_presets(url)
    if args.lite:
        presets = {k: v for k, v in presets.items() if k in ("H2", "H3", "H4")}
    # Phase 2 (Playwright headless) 는 Phase 1 과 결과 의존성 없음 — 동시 시작해 wall-clock 단축.
    # Phase 3+ 부터가 Phase 2 산출물(captured_headers / traffic.har / page_html) 의존이라 그 전에 join.
    _phase2_ex: ThreadPoolExecutor | None = None
    _phase2_future = None
    _do_headless = not args.no_headless and headless_available()
    if _do_headless:
        print("\n[Phase 2] Playwright headless w/ HAR capture ... (Phase 1 과 병렬 시작)")
        _phase2_ex = ThreadPoolExecutor(max_workers=1)
        _phase2_future = _phase2_ex.submit(
            fetch_with_capture,
            url=url,
            out_dir=out_dir,
            target="list",
            headless=not args.headful_debug,
            baseline_blocked=blocked,
        )
    elif not headless_available():
        print("\n[Phase 2] skipped — playwright not installed")

    print(f"\n[Phase 1] static GET ({'/'.join(presets)}) ...")
    # 같은 URL 을 헤더만 바꿔 N번 두드리는 거라 순차 실행 + sleep 의 가치가 낮음 → 병렬.
    # 결과 순서는 presets dict 순서 유지 (ThreadPoolExecutor.map).
    def _do_preset(item: tuple[str, dict]) -> tuple[str, Result]:
        preset_name, headers = item
        return preset_name, fetch_static(
            strategy=f"S1.{preset_name}",
            target="list",
            url=url,
            headers=headers,
            out_dir=out_dir,
            body_name=f"s1.{preset_name}",
            baseline_blocked=blocked,
        )

    static_results: list[Result] = []
    with ThreadPoolExecutor(max_workers=max(1, len(presets))) as _ex:
        for preset_name, r in _ex.map(_do_preset, presets.items()):
            static_results.append(r)
            print(f"  S1.{preset_name:<3} {r.status} {r.classification.value}")

    # H_user (--extra-header)
    if args.extra_header:
        _polite()
        h = dict(presets["H3"])
        for kv in args.extra_header:
            if "=" in kv:
                k, v = kv.split("=", 1)
                h[k.strip()] = v.strip()
        r = fetch_static(
            strategy="S1.Huser",
            target="list",
            url=url,
            headers=h,
            out_dir=out_dir,
            body_name="s1.Huser",
            baseline_blocked=blocked,
        )
        static_results.append(r)
        print(f"  S1.Huser  {r.status} {r.classification.value}")

    all_results.extend(static_results)

    # ---- Phase 2 join: 위에서 병렬로 띄운 headless 결과 회수. lite 모드도 headless 는 항상 돈다 ----
    # (HAR 가 JSON API 발견·렌더 DOM·통과헤더 확보의 핵심. lite 의 "경량"은 외부·유료·login 스킵임)
    headless: Result | None = None
    if _phase2_future is not None:
        headless = _phase2_future.result()
        print(f"\n[Phase 2 result] S4 {headless.status} {headless.classification.value}  {' '.join(headless.notable[:3])}")
        all_results.append(headless)
    if _phase2_ex is not None:
        _phase2_ex.shutdown()

    # ---- Phase 3: S1.Hcap (캡처 헤더로 정적 재시도) ----
    captured_retry: Result | None = None
    captured = load_captured_headers(out_dir, target="list") if headless is not None else {}
    if captured:
        print("\n[Phase 3] static retry with captured headers (S1.Hcap) ...")
        _polite()
        captured_retry = fetch_static(
            strategy="S1.Hcap",
            target="list",
            url=url,
            headers=merge_captured(captured),
            out_dir=out_dir,
            body_name="s1.Hcap",
            baseline_blocked=blocked,
        )
        print(f"  S1.Hcap    {captured_retry.status} {captured_retry.classification.value}")
        all_results.append(captured_retry)

    # ---- Phase 4: Login (auto-trigger or --login forced) + S1L ----
    s1l: Result | None = None
    needs_login = any(r.classification == Classification.LOGIN_REQUIRED for r in all_results)
    forced_login = args.login
    if args.lite and (needs_login or forced_login):
        print("\n[Phase 4] skipped (lite) — LOGIN_REQUIRED 감지됨. 자동 등록은 거부 대상.")
    if (needs_login or forced_login) and not args.no_login and not args.lite:
        if not headful_available():
            print("\n[Phase 4] login requested but Playwright not installed.")
            print("  설치 후 다시 실행하세요:")
            print("    pip install playwright playwright-stealth")
            print("    playwright install chromium")
        else:
            why = "LOGIN_REQUIRED detected" if needs_login else "--login forced"
            print(f"\n[Phase 4] {why} → headful trigger ...")
            state_p = state_file(slug)
            s5 = ensure_login_and_fetch(
                url=url, slug=slug, state_path=state_p, out_dir=out_dir,
            )
            all_results.append(s5)
            print(f"  S5         {s5.status} {s5.classification.value}")

            # S1L: 로그인 후 쿠키만 주입해 정적 재시도 (어댑터가 가벼운 httpx로 가능한지)
            cookies = cookies_from_state(state_p, url)
            if cookies:
                _polite()
                s1l = fetch_static(
                    strategy="S1L",
                    target="list",
                    url=url,
                    headers=presets["H3"],
                    cookies=cookies,
                    out_dir=out_dir,
                    body_name="s1L",
                    baseline_blocked=blocked,
                )
                all_results.append(s1l)
                print(f"  S1L        {s1l.status} {s1l.classification.value}")
            else:
                print("  S1L 스킵: state.json에서 도메인 쿠키를 추출하지 못함")

    # ---- Phase 5: external + paid ----
    external_results: list[Result] = []
    paid_results: list[Result] = []
    if args.lite:
        print("\n[Phase 5] skipped (lite) — Jina/Firecrawl/Crawl4AI/유료 스킵")
    else:
        print("\n[Phase 5] external & paid services ...")
        polite_sleep(0.5, 1.0)
        jina = try_jina(url=url, out_dir=out_dir, baseline_blocked=blocked)
        external_results.append(jina)
        print(f"  Jina       {jina.status} {jina.classification.value}")

        if args.firecrawl:
            polite_sleep(0.5, 1.0)
            fc = try_firecrawl(url=url, out_dir=out_dir, project_root=PROJECT_ROOT, baseline_blocked=blocked)
            external_results.append(fc)
            print(f"  Firecrawl  {fc.status} {fc.classification.value}  {' '.join(fc.notable[:2])}")

        if not args.no_crawl4ai:
            polite_sleep(0.5, 1.0)
            c4 = try_crawl4ai(url=url, out_dir=out_dir, baseline_blocked=blocked)
            external_results.append(c4)
            print(f"  Crawl4AI   {c4.status} {c4.classification.value}  {' '.join(c4.notable[:2])}")

        if not args.no_paid:
            keys = PaidKeys.from_env_and_args(args)
            paid_results = try_all_paid(url=url, keys=keys, out_dir=out_dir)
            for r in paid_results:
                print(f"  {r.strategy:<10} {r.status} {r.classification.value}  {' '.join(r.notable[:2])}")

    all_results.extend(external_results)
    all_results.extend(paid_results)

    # ---- Phase 6: discovery ----
    print("\n[Phase 6] feed/robots discovery ...")
    page_html = ""
    if headless is not None and headless.body_path:
        page_html = Path(headless.body_path).read_text(encoding="utf-8", errors="replace")
    elif static_results:
        for r in static_results:
            if r.classification == Classification.OK and r.body_path:
                page_html = Path(r.body_path).read_text(encoding="utf-8", errors="replace")
                break
    feeds = discover_feeds(page_url=url, page_html=page_html, out_dir=out_dir)
    robots_info = read_robots(page_url=url, out_dir=out_dir)
    print(f"  feeds: {len(feeds.get('candidates') or [])} candidates")
    print(f"  robots: status={robots_info.get('status')} crawl_delay={robots_info.get('crawl_delay')}")

    # ---- Hydration & Phase 7: list candidates ----
    print("\n[Phase 7] list candidates ...")
    hydration_blob = extract_hydration(page_html)
    (out_dir / "hydration.json").write_text(
        __import__("json").dumps(
            {k: (v if isinstance(v, dict) and "_parse_error" in v else "<json>") for k, v in hydration_blob.items()},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    hydration_lists: list[dict] = []
    for key, blob in hydration_blob.items():
        if isinstance(blob, dict):
            hits = find_list_in_json(blob)
            for h in hits:
                h["root"] = key
                hydration_lists.append(h)

    html_lists = html_repeating_patterns(page_html, base_url=url)
    inline_js_lists = extract_inline_data(page_html)

    har_path = out_dir / "traffic.har"
    if not har_path.exists():
        har_path = out_dir / "traffic.list.har"
    json_api_lists = traffic_api_candidates(har_path, page_url=url) if har_path.exists() else []

    first_article_url = pick_first_article_url(
        html_candidates=html_lists,
        json_api_candidates=json_api_lists,
        hydration_candidates=hydration_lists,
        base_url=url,
        page_html=page_html,
    )
    write_list_candidates(
        out_dir,
        html_candidates=html_lists,
        json_api_candidates=json_api_lists,
        hydration_candidates=hydration_lists,
        first_article_url=first_article_url,
        inline_js_candidates=inline_js_lists,
    )
    print(f"  HTML 반복 패턴: {len(html_lists)}건")
    print(f"  JSON API 후보: {len(json_api_lists)}건 (관련도순)")
    print(f"  Hydration 후보: {len(hydration_lists)}건")
    print(f"  인라인 JS/JSON 데이터 후보: {len(inline_js_lists)}건")
    print(f"  첫 글 URL: {first_article_url}")

    # ---- Phase 8: replay ----
    # lite 에서도 replay 는 돈다(JSON API 후보를 httpx 로 재현해 standalone 동작 확인 — httpx_json config 에 필수 정보).
    if not args.no_replay and json_api_lists:
        print("\n[Phase 8] replay candidate APIs ...")
        replays = replay_all(json_api_lists, out_dir)
        for r in replays:
            print(f"  {r.strategy} {r.url[:70]} → {r.status} {r.classification.value}")
            all_results.append(r)

    # ---- Phase 9: article entry ----
    article_result: Result | None = None
    if first_article_url:
        print("\n[Phase 9] article entry probe ...")
        # 목록이 정적 OK였다면 정적으로, 아니면 headless로
        static_ok = next((r for r in static_results if r.classification == Classification.OK), None)
        if static_ok is not None:
            _polite()
            article_result = fetch_static(
                strategy=f"S1.{static_ok.strategy.split('.')[-1]}.article",
                target="article",
                url=first_article_url,
                headers=presets[static_ok.strategy.split(".")[-1]] if static_ok.strategy.split(".")[-1] in presets else presets["H3"],
                out_dir=out_dir,
                body_name="article",
                baseline_blocked=blocked,
            )
        elif headless is not None and headless_available():
            article_result = fetch_with_capture(
                url=first_article_url,
                out_dir=out_dir,
                target="article",
                headless=not args.headful_debug,
                baseline_blocked=blocked,
            )
        if article_result is not None:
            all_results.append(article_result)
            print(f"  {article_result.strategy} {article_result.status} {article_result.classification.value}")

    # ---- Phase 9b: article-by-click (직접 GET 으론 다른 데로 튕기는 클라이언트 라우트 / href=javascript: 목록 대응) ----
    click_meta: dict = {}
    do_click = (not args.no_article_click and not args.no_headless and headless_available()
                and headless is not None and bool(first_article_url or html_lists))
    if do_click and args.lite:
        # lite 에선 직접 GET 으로 *진짜 글로 보이는* URL 의 본문 페이지를 이미 잘 받았으면 클릭 probe 생략(시간 절약).
        # 단, first_article_url 이 None 이거나(모든 행 href 가 javascript:) 글 ID 숫자가 없으면(메뉴/카테고리 링크였을 수 있음)
        # — 이 기능의 주 타깃 — got_body 여도 클릭 probe 를 돌린다.
        got_body = (article_result is not None
                    and article_result.classification == Classification.OK
                    and article_result.body_path
                    and Path(article_result.body_path).is_file()
                    and Path(article_result.body_path).stat().st_size > 8000)
        looks_like_real_article_url = bool(first_article_url and re.search(r"\d{3,}", first_article_url))
        if got_body and looks_like_real_article_url:
            do_click = False
    if do_click:
        print("\n[Phase 9b] article-by-click probe (목록에서 글 링크 클릭 → 최종 페이지/URL/HAR 캡처) ...")
        try:
            click_result, click_meta = fetch_article_by_click(
                list_url=url, out_dir=out_dir,
                headless=not args.headful_debug, baseline_blocked=blocked,
            )
            all_results.append(click_result)
            _note = click_meta.get("note")
            print(f"  {click_result.strategy} {click_result.status} {click_result.classification.value}  "
                  f"resolved={click_meta.get('resolved_url')}" + (f"  ({_note})" if _note else ""))
        except Exception as e:  # noqa: BLE001
            print(f"  article-by-click 실패: {type(e).__name__}: {e}")

    # ---- Phase 10: diagnose + summary ----
    print("\n[Phase 10] diagnose + write summary ...")
    diag = diagnose(
        slug=slug,
        url=url,
        baseline=baseline,
        static_results=static_results,
        headless=headless,
        captured_retry=captured_retry,
        s1l=s1l,
        external_results=external_results,
        paid_results=paid_results,
        list_candidates_path=out_dir / "list_candidates.json",
        article_result=article_result,
        robots_info=robots_info,
    )
    # GoodbyeDPI 비교 안내를 진단 노트에 추가
    diag.notes.extend(gdpi_advice(env))

    write_summary(
        out_dir=out_dir,
        slug=slug,
        url=url,
        baseline=baseline,
        all_results=all_results,
        diagnosis=diag,
        environment=env,
    )
    print(f"\n[probe] done. see: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
