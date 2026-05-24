"""사이트 정찰 도구 CLI.

사용:
    python scripts/probe.py "<URL>"
"""
from __future__ import annotations

import argparse
import contextvars as _cv
import multiprocessing as mp
import os
import queue
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가 (scripts/에서 패키지 import 가능하게)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.tracing import start_trace, current_trace
from probe.baseline import baseline_check, is_baseline_blocked
from probe.diagnose import diagnose
from probe.environment import capture as capture_environment, gdpi_advice
from probe.discover import discover_feeds, fetch_sitemaps, read_robots
from probe.extract import (
    all_same_host_patterns_in_nav,
    article_meta_signals,
    html_repeating_patterns,
    pick_first_article_url,
    list_row_external_host,
    list_row_interactive_action_text,
    runtime_id_candidates,
    traffic_api_candidates,
    write_list_candidates,
    detect_wordpress_platform,
    detect_discourse_platform,
    detect_common_platform,
    detect_xenforo_platform,
    detect_medium_custom_domain,
    detect_lemmy_platform,
    detect_mastodon_platform,
    detect_misskey_platform,
    detect_pixelfed_platform,
    detect_peertube_platform,
    detect_mbin_platform,
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

HEADLESS_JOIN_CAP_S = float(os.environ.get("PROBE_HEADLESS_JOIN_CAP_S", "45"))


def _headless_timeout_result(*, url: str, target: str, started: float, cap_s: float) -> Result:
    strategy = "S4.click" if target == "article_click" else ("S4" if target == "list" else "S4.article")
    return Result(
        strategy=strategy,
        target="article" if target == "article_click" else target,
        url=url,
        duration_ms=int((time.perf_counter() - started) * 1000),
        classification=Classification.UNKNOWN_ERROR,
        notable=[f"headless wall-clock cap exceeded ({cap_s:g}s); degraded"],
        error=f"headless_timeout: {cap_s:g}s",
    )


def _headless_error_result(*, url: str, target: str, started: float, error: str) -> Result:
    strategy = "S4.click" if target == "article_click" else ("S4" if target == "list" else "S4.article")
    return Result(
        strategy=strategy,
        target="article" if target == "article_click" else target,
        url=url,
        duration_ms=int((time.perf_counter() - started) * 1000),
        classification=Classification.UNKNOWN_ERROR,
        notable=["headless probe failed"],
        error=error,
    )


def _headless_child(kind: str, kwargs: dict, out_q) -> None:
    # 자식 process 에도 RSS guard 박음 — Phase 9b heavy SPA 누적은 *이 spawn 자식 안에서* 일어남
    # (probe.py 본체 process 에서는 7.5GB 안 봄). 2026-05-24 podcastindex 재현으로 검증됨.
    _start_memory_guard()
    try:
        if kind == "capture":
            out_q.put(("ok", fetch_with_capture(**kwargs)))
        elif kind == "click":
            out_q.put(("ok", fetch_article_by_click(**kwargs)))
        else:
            out_q.put(("err", f"unknown headless child kind: {kind}"))
    except BaseException as e:  # noqa: BLE001
        out_q.put(("err", f"{type(e).__name__}: {e}"))


def _terminate_process_tree(proc) -> None:
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            return
        except Exception:  # noqa: BLE001
            pass
    proc.terminate()


def _poll_child_memory(proc, *, cap_s: float) -> bool:
    """부모 process 가 자식 RSS 폴링 → 임계 초과 시 terminate. proc.join(cap_s) 대체.

    2026-05-24 박힘 — 자식 안 daemon thread 가 playwright greenlet 의 GIL 독점으로 안 깨우는
    문제 (podcastindex.org Phase 9b 재현). 부모는 free CPU 라 polling 이 정상.

    임계 = `PROBE_MEMORY_GUARD_MB` env (default 3500MB). N100 12GB - baseline 5GB = 7GB 여유의
    50% 선. concurrency 5 정상 case 와 충돌 X.

    Returns True if killed by memory guard, False if completed normally (또는 timeout 만남 —
    그 경우 caller 가 proc.is_alive() 로 후속 처리).
    """
    threshold_mb = int(os.environ.get("PROBE_MEMORY_GUARD_MB", "3500"))
    poll_s = float(os.environ.get("PROBE_MEMORY_GUARD_POLL_S", "1.0"))
    status_path = Path(f"/proc/{proc.pid}/status") if os.path.exists("/proc") else None
    sys.stderr.write(f"[probe-guard] arm: child_pid={proc.pid} threshold={threshold_mb}MB cap_s={cap_s}s status_exists={status_path is not None}\n")
    sys.stderr.flush()
    if status_path is None:
        proc.join(cap_s)
        return False
    deadline = time.perf_counter() + cap_s
    peak_mb = 0
    tick_n = 0
    while time.perf_counter() < deadline:
        tick_n += 1
        if not proc.is_alive():
            return False
        try:
            if not status_path.exists():
                # 자식 이미 사라짐
                return False
            for line in status_path.read_text().splitlines():
                if line.startswith("VmRSS:"):
                    rss_mb = int(line.split()[1]) // 1024
                    if rss_mb > peak_mb:
                        peak_mb = rss_mb
                    if tick_n <= 3 or tick_n % 5 == 0:
                        sys.stderr.write(f"[probe-guard] tick {tick_n}: pid={proc.pid} rss={rss_mb}MB peak={peak_mb}MB\n")
                        sys.stderr.flush()
                    if rss_mb > threshold_mb:
                        sys.stderr.write(
                            f"[probe] ❌ MEMORY GUARD: child PID={proc.pid} RSS={rss_mb}MB > "
                            f"threshold={threshold_mb}MB (peak={peak_mb}MB) — terminating.\n"
                        )
                        sys.stderr.flush()
                        _terminate_process_tree(proc)
                        proc.join(3)
                        return True
                    break
        except (FileNotFoundError, ProcessLookupError):
            return False
        except Exception:  # noqa: BLE001
            pass
        # 짧게 sleep 후 재폴 — proc.join 으로 cap_s 까지 한 번에 기다리면 폴링 못함.
        proc.join(timeout=poll_s)
    return False


def _run_headless_child(kind: str, kwargs: dict, *, cap_s: float, target: str) -> Result | tuple[Result, dict]:
    started = time.perf_counter()
    url = str(kwargs.get("url") or kwargs.get("list_url") or "")
    if cap_s <= 0:
        if kind == "capture":
            return fetch_with_capture(**kwargs)
        return fetch_article_by_click(**kwargs)

    ctx = mp.get_context("spawn")
    out_q = ctx.Queue(maxsize=1)
    proc = ctx.Process(target=_headless_child, args=(kind, kwargs, out_q), daemon=True)
    proc.start()
    # 부모가 자식 RSS 폴링 — 자식 안 daemon thread guard 는 playwright greenlet 이 GIL 독점 시
    # 안 깨우는 문제 (2026-05-24 podcastindex 재현으로 검증). 부모는 free CPU 라 정상 작동.
    memory_killed = _poll_child_memory(proc, cap_s=cap_s)
    if memory_killed:
        # 자식 RSS 임계 초과 → 부모가 kill. 부모 probe.py 도 rc=99 로 즉시 종료 (register 가
        # ProbeMemoryGuardError 경로로 capability_blocked rc=5 분류).
        sys.stderr.write(
            f"[probe] ❌ MEMORY GUARD (parent-side poll): child RSS exceeded threshold — "
            f"probe aborted (target={target}, url={url}).\n"
        )
        sys.stderr.flush()
        os._exit(_MEMORY_GUARD_RC)
    if proc.is_alive():
        _terminate_process_tree(proc)
        proc.join(3)
        timeout_result = _headless_timeout_result(url=url, target=target, started=started, cap_s=cap_s)
        if kind == "click":
            return timeout_result, {"requested_url": url, "resolved_url": None, "status": None,
                                    "clicked_text": None, "clicked_href": None,
                                    "note": timeout_result.error}
        return timeout_result

    # 자식이 memory guard 로 self-kill (rc=99) — 부모 probe.py 도 같은 rc 로 즉시 종료.
    # register.py 의 ProbeMemoryGuardError 경로가 capability_blocked rc=5 로 변환.
    # 안 그러면 probe.py 가 Phase 9b 실패만 기록하고 다른 phase 계속 → digest 진행 → rc=0/1
    # 으로 끝나 register 가 capability 분류 못 함.
    if proc.exitcode == _MEMORY_GUARD_RC:
        sys.stderr.write(
            f"[probe] ❌ propagating memory guard rc={_MEMORY_GUARD_RC} from headless child "
            f"(target={target}, url={url}) — probe aborted to protect notice-bot.service.\n"
        )
        sys.stderr.flush()
        os._exit(_MEMORY_GUARD_RC)
    try:
        status, payload = out_q.get_nowait()
    except queue.Empty:
        err = f"headless child exited without result (exitcode={proc.exitcode})"
        error_result = _headless_error_result(url=url, target=target, started=started, error=err)
        if kind == "click":
            return error_result, {"requested_url": url, "resolved_url": None, "status": None,
                                  "clicked_text": None, "clicked_href": None, "note": err}
        return error_result
    if status == "ok":
        return payload
    error_result = _headless_error_result(url=url, target=target, started=started, error=str(payload))
    if kind == "click":
        return error_result, {"requested_url": url, "resolved_url": None, "status": None,
                              "clicked_text": None, "clicked_href": None, "note": str(payload)}
    return error_result


def _bounded_fetch_with_capture(**kwargs) -> Result:
    return _run_headless_child("capture", kwargs, cap_s=HEADLESS_JOIN_CAP_S, target=str(kwargs.get("target") or "list"))  # type: ignore[return-value]


def _bounded_fetch_article_by_click(**kwargs) -> tuple[Result, dict]:
    return _run_headless_child("click", kwargs, cap_s=HEADLESS_JOIN_CAP_S, target="article_click")  # type: ignore[return-value]


def _static_results_are_hard_login(static_results: list[Result]) -> bool:
    return (
        bool(static_results)
        and all(r.classification == Classification.LOGIN_REQUIRED for r in static_results)
        and any("redirected to login" in n for r in static_results for n in (r.notable or []))
    )


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


_MEMORY_GUARD_RC = 99


def _start_memory_guard() -> None:
    """probe 프로세스 RSS 가 임계 초과하면 os._exit(99) — N100 12GB OOM 방어선.

    2026-05-24 podcast batch 박힘: podcastindex.org probe Phase 9b (heavy SPA article-by-click)
    가 python(playwright sync API) RSS 를 +18s 200MB → +54s 7459MB 직선 누적시켜 kernel global
    OOM 발동 → notice-bot.service `oom-kill` (tailscaled 도 함께 victim). 정확 leak 지점은 별도
    조사(tracemalloc) 필요하나, 그 결과와 *무관하게* 한 사이트가 service 전체를 죽이지 못하게
    하는 첫 방어선이 필요.

    임계 = `PROBE_MEMORY_GUARD_MB` env (default 3500MB). N100(12GB total - 5GB baseline = 7GB
    여유) 의 50% 선. concurrency 5 정상 case (각 ~200MB) 와는 충돌 X, podcastindex 류 폭주
    case 만 차단.

    daemon thread 라 normal exit 시 자동 소멸. Linux 만 동작 (/proc/self/status) — Windows/macOS
    는 silently skip (개발 박스 OOM 없음).
    """
    threshold_mb = int(os.environ.get("PROBE_MEMORY_GUARD_MB", "3500"))
    poll_s = float(os.environ.get("PROBE_MEMORY_GUARD_POLL_S", "1.0"))
    status_path = Path("/proc/self/status")
    if not status_path.exists():
        return  # non-Linux

    def _watch() -> None:
        peak_mb = 0
        while True:
            try:
                for line in status_path.read_text().splitlines():
                    if line.startswith("VmRSS:"):
                        rss_kb = int(line.split()[1])
                        rss_mb = rss_kb // 1024
                        if rss_mb > peak_mb:
                            peak_mb = rss_mb
                        if rss_mb > threshold_mb:
                            sys.stderr.write(
                                f"[probe] ❌ MEMORY GUARD: RSS={rss_mb}MB > threshold={threshold_mb}MB — "
                                f"probe killed cleanly to protect notice-bot.service (peak={peak_mb}MB). "
                                f"이 사이트는 OOM blower (heavy SPA 추정) — capability_blocked 분류.\n"
                            )
                            sys.stderr.flush()
                            os._exit(_MEMORY_GUARD_RC)
                        break
            except Exception:
                pass
            time.sleep(poll_s)

    t = threading.Thread(target=_watch, name="probe-memory-guard", daemon=True)
    t.start()


def main(argv: list[str]) -> int:
    _start_memory_guard()
    args = parse_args(argv)
    url: str = args.url
    slug = url_to_slug(url)
    with start_trace("probe", attrs={"url": url, "slug": slug, "lite": bool(args.lite)}):
        return _run(args, url, slug)


def _run(args: argparse.Namespace, url: str, slug: str) -> int:
    tr = current_trace()
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

    with tr.span("env_capture"):
        env = capture_environment(out_dir)
    print(f"[env] platform={env['platform']}  outbound_ip_local={env['outbound_ip_local']}")
    print(f"[env] GoodbyeDPI: running={env['goodbyedpi_running']} ({env['goodbyedpi_info']})\n")

    all_results: list[Result] = []

    # ---- Phase 0: baseline ----
    print("[Phase 0] baseline ping ...")
    with tr.span("phase0_baseline"):
        baseline = baseline_check(url)
        blocked = is_baseline_blocked(baseline)
    for r in baseline.values():
        print(f"  {r.strategy} {r.url} → {r.status} {r.classification.value}")

    # baseline 이 httpx 로 못 뚫렸으면(blocked) — Cloudflare/봇보호 류라 같은 httpx 를 또 두드려봐야
    # 전부 ReadTimeout 까지 꽉 기다린다 (Phase 1/3/6 각 10~25s 낭비; 페이지는 Phase 2 headless 가 2s 에 뜸).
    # 그 페이즈들 httpx 한도를 짧게 잡아 fail-fast — blocked 사이트는 어차피 빈 결과라 손실 없음.
    if blocked:
        print("  → baseline httpx blocked: Phase 1/3/6 httpx fail-fast (4s)")
    _http_to = 4.0 if blocked else 15.0
    _disc_to = 4.0 if blocked else 10.0

    # ---- Phase 1: static GET with header presets ----
    presets = all_presets(url)
    if args.lite:
        presets = {k: v for k, v in presets.items() if k in ("H2", "H3", "H4")}
    _do_headless = not args.no_headless and headless_available()

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
            timeout=_http_to,
        )

    static_results: list[Result] = []
    with tr.span("phase1_static_get", attrs={"presets": ",".join(presets.keys())}):
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
            timeout=_http_to,
        )
        static_results.append(r)
        print(f"  S1.Huser  {r.status} {r.classification.value}")

    all_results.extend(static_results)

    # ---- Phase 2: Playwright headless. lite 모드도 headless 는 돈다 ----
    # (HAR 가 JSON API 발견·렌더 DOM·통과헤더 확보의 핵심. lite 의 "경량"은 외부·유료·login 스킵임)
    # 단, 정적 진입이 전부 hard login redirect 면 headless 로 얻을 추가 신호가 없고 heavy login SPA 에서
    # process exit 이 지연될 수 있어 fail-fast 한다.
    headless: Result | None = None
    static_hard_login = _static_results_are_hard_login(static_results)
    if static_hard_login:
        print("\n[Phase 2] skipped — Phase 1 hard LOGIN_REQUIRED redirect (headless would hit login SPA)")
    elif _do_headless:
        print(f"\n[Phase 2] Playwright headless w/ HAR capture ... (cap={HEADLESS_JOIN_CAP_S:g}s)")
        with tr.span("phase2_headless_har_capture", attrs={"target": "list", "cap_s": HEADLESS_JOIN_CAP_S}):
            headless = _bounded_fetch_with_capture(
                url=url,
                out_dir=out_dir,
                target="list",
                headless=not args.headful_debug,
                baseline_blocked=blocked,
            )
        print(f"\n[Phase 2 result] S4 {headless.status} {headless.classification.value}  {' '.join(headless.notable[:3])}")
        all_results.append(headless)
    elif args.no_headless:
        print("\n[Phase 2] skipped — --no-headless")
    elif not headless_available():
        print("\n[Phase 2] skipped — playwright not installed")

    # ---- Phase 3: S1.Hcap (캡처 헤더로 정적 재시도) ----
    captured_retry: Result | None = None
    captured = load_captured_headers(out_dir, target="list") if headless is not None else {}
    if captured:
        print("\n[Phase 3] static retry with captured headers (S1.Hcap) ...")
        with tr.span("phase3_hcap_static_retry"):
            _polite()
            captured_retry = fetch_static(
                strategy="S1.Hcap",
                target="list",
                url=url,
                headers=merge_captured(captured),
                out_dir=out_dir,
                body_name="s1.Hcap",
                baseline_blocked=blocked,
                timeout=_http_to,
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
            with tr.span("phase4_login_headful", attrs={"why": why}):
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
        with tr.span("phase5_external_paid"):
            with tr.span("phase5_jina"):
                polite_sleep(0.5, 1.0)
                jina = try_jina(url=url, out_dir=out_dir, baseline_blocked=blocked)
            external_results.append(jina)
            print(f"  Jina       {jina.status} {jina.classification.value}")

            if args.firecrawl:
                with tr.span("phase5_firecrawl"):
                    polite_sleep(0.5, 1.0)
                    fc = try_firecrawl(url=url, out_dir=out_dir, project_root=PROJECT_ROOT, baseline_blocked=blocked)
                external_results.append(fc)
                print(f"  Firecrawl  {fc.status} {fc.classification.value}  {' '.join(fc.notable[:2])}")

            if not args.no_crawl4ai:
                with tr.span("phase5_crawl4ai"):
                    polite_sleep(0.5, 1.0)
                    c4 = try_crawl4ai(url=url, out_dir=out_dir, baseline_blocked=blocked)
                external_results.append(c4)
                print(f"  Crawl4AI   {c4.status} {c4.classification.value}  {' '.join(c4.notable[:2])}")

            if not args.no_paid:
                with tr.span("phase5_paid"):
                    keys = PaidKeys.from_env_and_args(args)
                    paid_results = try_all_paid(url=url, keys=keys, out_dir=out_dir)
                for r in paid_results:
                    print(f"  {r.strategy:<10} {r.status} {r.classification.value}  {' '.join(r.notable[:2])}")

    all_results.extend(external_results)
    all_results.extend(paid_results)

    # ---- Phase 6: discovery (백그라운드) ----
    # discover_feeds(6 path 동시 GET) + read_robots — 양쪽 모두 HTTP 라 1~3s.
    # Phase 7~9b 와 결과 의존성 없음 (Phase 10 diagnose 만 소비). 백그라운드로 띄우고 Phase 10 직전 join.
    page_html = ""
    if headless is not None and headless.classification == Classification.OK and headless.body_path:
        page_html = Path(headless.body_path).read_text(encoding="utf-8", errors="replace")
    elif static_results:
        for r in static_results:
            if r.classification == Classification.OK and r.body_path:
                page_html = Path(r.body_path).read_text(encoding="utf-8", errors="replace")
                break

    print("\n[Phase 6] feed/robots discovery ... (백그라운드 시작, Phase 7~9 와 병렬)")
    # with-block 으로 묶어 — Phase 7~9b 어디서 raise 해도 __exit__ 가 shutdown(wait=True) 보장.
    # 두 future 는 with 마지막에 회수, 각자 try/except 로 한쪽 실패가 다른쪽 회수를 막지 못하게.
    with ThreadPoolExecutor(max_workers=2) as _phase6_ex:
        def _traced_feeds():
            with current_trace().span("phase6_discover_feeds"):
                return discover_feeds(page_url=url, page_html=page_html, out_dir=out_dir, timeout=_disc_to)

        def _traced_robots():
            with current_trace().span("phase6_read_robots"):
                return read_robots(page_url=url, out_dir=out_dir, timeout=_disc_to)

        _feeds_fut = _phase6_ex.submit(_cv.copy_context().run, _traced_feeds)
        _robots_fut = _phase6_ex.submit(_cv.copy_context().run, _traced_robots)

        # ---- Hydration & Phase 7: list candidates ----
        print("\n[Phase 7] list candidates ...")
        with tr.span("phase7_list_candidates"):
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
            runtime_ids = runtime_id_candidates(page_html)

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
            row_external_host = list_row_external_host(
                html_candidates=html_lists,
                base_url=url,
            )
            row_interactive_action = list_row_interactive_action_text(
                html_candidates=html_lists,
            )
            nav_only_same_host = all_same_host_patterns_in_nav(
                html=page_html or "",
                html_candidates=html_lists,
                base_url=url,
            )
            meta_signals = article_meta_signals(html=page_html or "")
            wordpress_platform = detect_wordpress_platform(html=page_html or "", base_url=url)
            discourse_platform = detect_discourse_platform(html=page_html or "", base_url=url)
            common_platform = detect_common_platform(html=page_html or "", base_url=url)
            xenforo_platform = detect_xenforo_platform(html=page_html or "", base_url=url)
            medium_custom_domain = detect_medium_custom_domain(html=page_html or "", base_url=url)
            lemmy_platform = detect_lemmy_platform(html=page_html or "", base_url=url)
            mastodon_platform = detect_mastodon_platform(html=page_html or "", base_url=url)
            misskey_platform = detect_misskey_platform(html=page_html or "", base_url=url)
            pixelfed_platform = detect_pixelfed_platform(html=page_html or "", base_url=url)
            peertube_platform = detect_peertube_platform(html=page_html or "", base_url=url)
            mbin_platform = detect_mbin_platform(html=page_html or "", base_url=url)
            write_list_candidates(
                out_dir,
                base_url=url,
                html_candidates=html_lists,
                json_api_candidates=json_api_lists,
                hydration_candidates=hydration_lists,
                first_article_url=first_article_url,
                inline_js_candidates=inline_js_lists,
                runtime_ids=runtime_ids,
                row_external_host=row_external_host,
                row_interactive_action=row_interactive_action,
                nav_only_same_host=nav_only_same_host,
                article_meta_signals=meta_signals,
                wordpress_platform=wordpress_platform,
                discourse_platform=discourse_platform,
                common_platform=common_platform,
                xenforo_platform=xenforo_platform,
                medium_custom_domain=medium_custom_domain,
                lemmy_platform=lemmy_platform,
                mastodon_platform=mastodon_platform,
                misskey_platform=misskey_platform,
                pixelfed_platform=pixelfed_platform,
                peertube_platform=peertube_platform,
                mbin_platform=mbin_platform,
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
            with tr.span("phase8_replay", attrs={"n_apis": len(json_api_lists)}):
                replays = replay_all(json_api_lists, out_dir)
            for r in replays:
                print(f"  {r.strategy} {r.url[:70]} → {r.status} {r.classification.value}")
                all_results.append(r)

        # ---- Phase 9: article entry ----
        article_result: Result | None = None
        if first_article_url:
            print("\n[Phase 9] article entry probe ...")
            with tr.span("phase9_article_entry"):
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
                    article_result = _bounded_fetch_with_capture(
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
            with tr.span("phase9b_article_by_click"):
                try:
                    click_result, click_meta = _bounded_fetch_article_by_click(
                        list_url=url, out_dir=out_dir,
                        headless=not args.headful_debug, baseline_blocked=blocked,
                    )
                    all_results.append(click_result)
                    _note = click_meta.get("note")
                    print(f"  {click_result.strategy} {click_result.status} {click_result.classification.value}  "
                          f"resolved={click_meta.get('resolved_url')}" + (f"  ({_note})" if _note else ""))
                except Exception as e:  # noqa: BLE001
                    print(f"  article-by-click 실패: {type(e).__name__}: {e}")

        # ---- Phase 6 join — 각 future 개별 try/except 로 한쪽 실패가 다른쪽 회수를 막지 못하게 ----
        with tr.span("phase6_join"):
            try:
                feeds = _feeds_fut.result()
            except Exception as _e_feeds:  # noqa: BLE001 — discover_feeds 의 ContractError 등
                print(f"  [Phase 6 feeds] fail: {type(_e_feeds).__name__}: {_e_feeds}")
                feeds = {"page_url": url, "candidates": []}
            try:
                robots_info = _robots_fut.result()
            except Exception as _e_robots:  # noqa: BLE001
                print(f"  [Phase 6 robots] fail: {type(_e_robots).__name__}: {_e_robots}")
                robots_info = {"url": "", "status": None, "crawl_delay": None, "disallow": [], "sitemaps": []}
        # sitemap fetch (robots 의 Sitemap: 라인 + 표준 경로 폴백) — robots 결과 의존이라 sequential.
        # hard login redirect 는 policy reject 로 끝나는 입력이라 sitemap 후보 회복이 의미 없고,
        # 일부 login SPA 의 sitemap 엔드포인트가 느리게 매달려 register timeout 을 잡아먹는다.
        if static_hard_login:
            sitemap_info = {"page_url": url, "sitemap_urls_tried": [], "candidates": [],
                            "stats": {"sitemap_count": 0, "fetched": 0, "errors": 0, "out_total": 0}}
            (out_dir / "sitemap.json").write_text(
                __import__("json").dumps(sitemap_info, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            # 사용자 URL 이 board root 아닐 때 후보 회복 — config_writer 가 i==1 부터 참조.
            with tr.span("phase6_fetch_sitemaps"):
                try:
                    sitemap_info = fetch_sitemaps(
                        page_url=url,
                        robots_sitemaps=robots_info.get("sitemaps") or [],
                        out_dir=out_dir,
                    )
                except Exception as _e_sm:  # noqa: BLE001
                    print(f"  [Phase 6 sitemap] fail: {type(_e_sm).__name__}: {_e_sm}")
                    sitemap_info = {"page_url": url, "sitemap_urls_tried": [], "candidates": [],
                                    "stats": {"sitemap_count": 0, "fetched": 0, "errors": 0, "out_total": 0}}
        print(f"\n[Phase 6 result] feeds: {len(feeds.get('candidates') or [])} candidates · "
              f"robots: status={robots_info.get('status')} crawl_delay={robots_info.get('crawl_delay')} "
              f"sitemaps={len(robots_info.get('sitemaps') or [])} · "
              f"sitemap_candidates: {len(sitemap_info.get('candidates') or [])}")

    # ---- Phase 10: diagnose + summary ----
    print("\n[Phase 10] diagnose + write summary ...")
    with tr.span("phase10_diagnose_summary"):
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
