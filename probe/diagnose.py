"""Phase 10: verdict + 권장 어댑터 방식."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .baseline import is_baseline_blocked
from .extract import static_vs_headless_check
from .types import Classification, Diagnosis, Result


_CERT_OR_DNS_ERROR_MARKERS = (
    "CERTIFICATE_VERIFY_FAILED",
    "Hostname mismatch",
    "SSL: ",
    "ERR_CERT_",
    "ERR_NAME_NOT_RESOLVED",           # Chromium/Playwright DNS resolution fail
    "[Errno -2]",                      # getaddrinfo EAI_NONAME
    "[Errno -3]",                      # EAI_AGAIN
    "[Errno -5]",                      # EAI_NODATA (No address associated with hostname — IPv6/IPv4 mismatch)
    "No address associated with hostname",
    "Name or service not known",
    "nodename nor servname provided",
    "Temporary failure in name resolution",
    "ConnectError",
    "Connection refused",
    "connection refused",
    "WinError 10061",
    "All connection attempts failed",
)


# notes 에 박히는 static_vs_headless trigger 메시지 *고정 prefix*. scripts/register.py 가 substring 매치로
# hint 트리거 — 메시지 reword 시 silent skip 방지를 위해 *상수* 로 export. 메시지 본문 수정 가능하지만
# 이 prefix 만은 *그대로* 유지해야 register.py 의 _extra_signal_hints 가 잡는다.
STATIC_INSUFFICIENT_SIZE_PREFIX = "정적 응답이 빈 shell"        # rule 1 = 강한 신호 (size + row-signal)
STATIC_INSUFFICIENT_REPEAT_PREFIX = "정적 응답 vs Playwright DOM"  # rule 2 = 약한 신호 (selector-level repeat diff)


def _read_list_candidates(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _is_cert_or_dns_error(err: Optional[str]) -> bool:
    if not err:
        return False
    return any(m in err for m in _CERT_OR_DNS_ERROR_MARKERS)


def _static_row_evidence(static_like_ok: list[Result], list_payload: dict) -> Optional[dict]:
    if not static_like_ok:
        return None
    patterns = list_payload.get("html_repeating_patterns") or []
    if not isinstance(patterns, list):
        return None

    best: Optional[dict] = None
    for item in patterns:
        if not isinstance(item, dict):
            continue
        try:
            child_count = int(item.get("child_count") or item.get("count") or 0)
        except (TypeError, ValueError):
            child_count = 0
        sample_url = item.get("sample_url") or list_payload.get("first_article_url")
        if child_count < 10 or not sample_url:
            continue
        if best is None or child_count > int(best.get("child_count") or 0):
            best = {**item, "child_count": child_count, "sample_url": sample_url}

    if not best:
        return None

    return {
        "strategy": static_like_ok[0].strategy,
        "selector": best.get("selector") or "?",
        "child_count": best.get("child_count"),
        "sample_url": best.get("sample_url"),
    }


def diagnose(
    *,
    slug: str,
    url: str,
    baseline: dict[str, Result],
    static_results: list[Result],
    headless: Optional[Result],
    captured_retry: Optional[Result],
    s1l: Optional[Result],
    external_results: list[Result],
    paid_results: list[Result],
    list_candidates_path: Path,
    article_result: Optional[Result],
    robots_info: dict,
) -> Diagnosis:
    notes: list[str] = []
    baseline_classes = [r.classification for r in baseline.values()]
    # B1(/) 또는 B2(/robots.txt) 중 *하나라도* OK 면 IP/도메인 차단 아님.
    # robots.txt 404 같은 흔한 케이스에서 all() 룰이 False positive 를 내던 모순을
    # baseline.is_baseline_blocked() 의 정의와 통일.
    baseline_ok = not is_baseline_blocked(baseline)
    baseline_bot_only = (
        bool(baseline_classes)
        and all(c == Classification.BLOCKED_BOT for c in baseline_classes)
    )
    # SSL cert mismatch / DNS resolution / connect 실패 — 사이트 자체가 죽었거나 운영 오설정.
    # 차단(BLOCKED)이 아니므로 별도 verdict 로 분리해서 register 메시지가 정확하게 나오게 한다.
    baseline_cert_broken = bool(baseline_classes) and all(
        c == Classification.UNKNOWN_ERROR for c in baseline_classes
    ) and any(
        _is_cert_or_dns_error(r.error) for r in baseline.values()
    )
    if baseline_bot_only:
        notes.append("baseline 도메인 루트도 봇 보호(Cloudflare 등)로 막힘 — 사이트 자체 정책, IP 차단은 아님")
    elif baseline_cert_broken:
        sample = next((r.error for r in baseline.values() if _is_cert_or_dns_error(r.error)), "")
        notes.append(
            "baseline ping 이 SSL 인증서/DNS/connect 단계에서 실패 — 사이트 운영 오설정 또는 사이트가 사라졌을 가능성. "
            f"샘플 에러: {sample}"
        )
    elif not baseline_ok:
        notes.append("baseline ping 일부 실패 — IP/도메인 차단 의심")

    # 가장 약한 통과 결정
    static_ok = [r for r in static_results if r.classification == Classification.OK]
    headless_ok = headless is not None and headless.classification == Classification.OK
    captured_ok = captured_retry is not None and captured_retry.classification == Classification.OK

    # static_vs_headless content 비교 — static 응답이 *빈 shell* (JS 가 카드/목록 그려야 하는 사이트) 인지 검증.
    # static_ok + headless_ok 둘 다 있을 때만 의미 있음. piku 처럼 같은 URL 정적=14kb·data-id=0 vs
    # Playwright=44kb·data-id=20 인 케이스 → static_insufficient=True → "정적 HTTP로 충분" verdict 정정.
    static_vs_headless: Optional[dict] = None
    static_like_ok = list(static_ok)
    if captured_ok and captured_retry is not None:
        static_like_ok.append(captured_retry)
    list_payload = _read_list_candidates(list_candidates_path)
    static_row_evidence = _static_row_evidence(static_like_ok, list_payload)
    if static_row_evidence:
        notes.append(
            "정적 HTML row 후보가 충분함 — "
            f"{static_row_evidence.get('strategy')} OK + selector "
            f"{static_row_evidence.get('selector')} cc={static_row_evidence.get('child_count')} "
            f"sample={static_row_evidence.get('sample_url')} 확인. "
            "Playwright DOM 이 더 크더라도 static rows 우선."
        )
    if static_like_ok and headless_ok and headless is not None:
        biggest_static = max(
            (r for r in static_like_ok if r.body_path),
            key=lambda r: (Path(r.body_path).stat().st_size if Path(r.body_path).exists() else 0),
            default=None,
        )
        if biggest_static is not None and biggest_static.body_path and headless.body_path:
            s_path = Path(biggest_static.body_path)
            h_path = Path(headless.body_path)
            if s_path.exists() and h_path.exists():
                static_vs_headless = static_vs_headless_check(
                    s_path.read_text(encoding="utf-8", errors="replace"),
                    h_path.read_text(encoding="utf-8", errors="replace"),
                    base_url=url,
                )
                if static_vs_headless.get("static_insufficient"):
                    trigger = static_vs_headless.get("trigger_rule") or "?"
                    if trigger == "size":
                        if not static_row_evidence:
                            # 강한 신호 — 정적 계열 응답이 진짜 빈 shell. 일반 정적뿐 아니라
                            # S1.Hcap 도 같은 빈 shell 이면 httpx 권장으로 되살리지 않는다.
                            static_ok = []
                            captured_ok = False
                            notes.append(
                                f"{STATIC_INSUFFICIENT_SIZE_PREFIX} — Playwright 응답이 정적보다 "
                                f"{static_vs_headless.get('ratio'):.1f}배 크고 row-like 요소 "
                                f"({static_vs_headless.get('row_signal_headless')} vs "
                                f"{static_vs_headless.get('row_signal_static')}) 만 잡힘. "
                                "JS 가 카드/목록 그리는 사이트 — strategy=playwright_html 필수."
                            )
                    elif trigger == "repeat":
                        # 약한 신호 — 정적 응답에도 콘텐츠 있지만 headless 에만 mosaic tile 다수 (humblebundle 류).
                        # static_ok 무효화 X (정적 httpx 로도 작동할 수 있음 — JSON island 직접 파싱 등).
                        # notes 로 LLM 에 *고려* 만 시킴.
                        notes.append(
                            f"⚠ {STATIC_INSUFFICIENT_REPEAT_PREFIX} 비교: headless 에만 mosaic/tile 류 반복 패턴 "
                            f"{static_vs_headless.get('repeat_anchors_headless')}개 추가됨 "
                            f"(정적 {static_vs_headless.get('repeat_anchors_static')}). "
                            "정적 HTML 의 <script id=*-json-data> 같은 JSON island 에서 클라이언트 JS 가 tile 렌더 가능성 — "
                            "그렇다면 strategy=playwright_html + list.wait_selector. 단, 정적 응답 안에 직접 파싱 가능한 "
                            "JSON 이 있으면 httpx_html + inline_js_data_candidates 도 검토."
                        )

    recommended_strategy: str
    recommended_headers_summary: str
    if static_ok:
        easiest = sorted(static_ok, key=lambda r: ("H1", "H2", "H3", "H4").index(r.strategy.split(".")[-1]) if "." in r.strategy else 99)[0]
        recommended_strategy = f"httpx ({easiest.strategy})"
        recommended_headers_summary = easiest.strategy
    elif captured_ok:
        recommended_strategy = "httpx + 캡처된 메인 문서 헤더 (S1.Hcap)"
        recommended_headers_summary = "S1.Hcap"
    elif headless_ok:
        recommended_strategy = "Playwright headless + stealth (S4)"
        recommended_headers_summary = "S4 (브라우저)"
    else:
        # 외부 서비스 통과 확인
        ext_ok = [r for r in external_results if r.classification == Classification.OK]
        paid_ok = [r for r in paid_results if r.classification == Classification.OK]
        if ext_ok:
            recommended_strategy = f"외부 서비스 ({ext_ok[0].strategy})"
        elif paid_ok:
            recommended_strategy = f"유료 API ({paid_ok[0].strategy})"
        else:
            recommended_strategy = "통과한 전략 없음 — 추가 검토 필요"
        recommended_headers_summary = "n/a"

    crawl_delay = robots_info.get("crawl_delay")
    interval = int(crawl_delay) if crawl_delay else 5

    list_summary = "n/a"
    list_lookup_failed = False
    html_n = api_n = hyd_n = 0
    if list_candidates_path.exists():
        try:
            payload = list_payload
            html_n = len(payload.get("html_repeating_patterns") or [])
            api_n = len(payload.get("traffic_json_api_candidates") or [])
            hyd_n = len(payload.get("hydration_list_candidates") or [])
            first = payload.get("first_article_url") or "(none)"
            list_summary = f"HTML {html_n}건, JSON API {api_n}건, hydration {hyd_n}건. 첫 글: {first}"
            # 글 목록 컨테이너는 잡혔는데 첫 글 URL이 None → 클라이언트 JS 라우팅 의심
            if not payload.get("first_article_url") and (html_n > 0 or hyd_n > 0):
                list_lookup_failed = True
        except Exception:
            pass

    article_ok = article_result is not None and article_result.classification == Classification.OK
    if article_result is None:
        notes.append("본문 진입 미수행 (목록 후보 없음 또는 글 URL 추출 실패)")

    # 글 목록 컨테이너는 발견됐는데 링크 추출 실패 → 클라이언트 JS 라우팅. Playwright 권장.
    if list_lookup_failed:
        notes.append(
            "글 목록 컨테이너는 발견됐으나 첫 글 URL 추출 실패 — "
            "글 링크가 정적 HTML에 없고 클라이언트 JS(예: Next.js <Link> 클릭 핸들러)로 라우팅되는 것으로 추정. "
            "Playwright 풀 로드(traffic.har)에서 클라이언트 fetch 엔드포인트 확인 필요."
        )
        if not headless_ok and not captured_ok:
            recommended_strategy = (
                "Playwright headless 필요 — 정적은 OK이나 글 링크가 클라이언트 라우팅이므로 "
                "traffic.har에서 데이터 fetch 엔드포인트 또는 Next.js RSC payload(/_next/data/...) 확인"
            )
            recommended_headers_summary = "n/a (Playwright)"

    verdict_parts = []
    # login 게이트 우선 — list 진입이 LOGIN_REQUIRED 인데 OK 진입이 하나도 없으면 로그인 벽.
    # notable 로 hard(redirect, 서버가 /login 으로 튕김) vs soft(본문 마커/form, 목록 가릴 수도 안 가릴 수도)
    # 구분 → register 가 hard 면 즉시 rc=2, soft 면 분류기로 board 여부 판정 (ADR 0007 §확장 2026-05-22).
    # (구) soft_404 regex 분기는 제거됨 — not-found 200 shell 은 register 의 분류기(not_found)가 arbiter.
    login_target_results: list[Result] = list(static_results)
    if headless is not None:
        login_target_results.append(headless)
    if captured_retry is not None:
        login_target_results.append(captured_retry)
    if s1l is not None:
        login_target_results.append(s1l)
    login_results = [r for r in login_target_results if r.classification == Classification.LOGIN_REQUIRED]
    ok_list_results = [r for r in login_target_results if r.classification == Classification.OK]
    if login_results and not ok_list_results:
        redirect = any("redirected to login" in n for r in login_results for n in (r.notable or []))
        verdict_parts.append("LOGIN_REDIRECT" if redirect else "LOGIN_MARKER")
        notes.append(
            "list 진입이 로그인 게이트로 분류됨 — "
            + ("서버가 /login 으로 redirect (hard 거부)." if redirect
               else "본문 로그인 마커/form 감지 (soft — register 분류기가 board 여부 판정).")
        )
    else:
        if baseline_bot_only:
            verdict_parts.append("CLOUDFLARE_PROTECTED_SITE")
        elif baseline_cert_broken:
            verdict_parts.append("CERT_OR_DNS_BROKEN")
        elif not baseline_ok:
            verdict_parts.append("BASELINE_BLOCKED")
        # 자체 WAF (KR IDC NHN/Naver/WAPPLES 패턴) — 모든 정적 진입이 HTTP 406 면 vendor 가 Cloudflare/Akamai 가
        # 아니라 origin 자체 WAF 가 UA/Accept-Language/TLS 콤보를 거른 것. register 가 "Cloudflare" 메시지 대신
        # curl_cffi 임퍼소네이트 트랙 안내하도록 별도 verdict 태그.
        # 2026-05-26 batch games-kr valofe×4 사례 (research_cloudflare_findings.md §G).
        if static_results and all(r.status == 406 for r in static_results):
            verdict_parts.append("WAF_406_BLOCK")
        if static_ok and not any("Cloudflare" in n for r in static_results for n in r.notable):
            verdict_parts.append("정적 HTTP로 충분")
        elif captured_ok:
            verdict_parts.append("캡처 헤더 주입 시 정적 가능")
        elif headless_ok:
            verdict_parts.append("JS 실행 필요 (Cloudflare 등)")

    # baseline 은 OK 인데 target URL 시도가 *전부 NOT_FOUND* 면 사이트 차단이 아니라 그 URL 자체가
    # 없음 (잘못된 URL 또는 글이 삭제됨). register.py 의 BLOCKED 메시지와 구분하기 위해 별도 verdict.
    if baseline_ok and not verdict_parts:
        target_results: list[Result] = list(static_results)
        if headless is not None:
            target_results.append(headless)
        primary_target_results = list(target_results)
        if captured_retry is not None:
            target_results.append(captured_retry)
        if s1l is not None:
            target_results.append(s1l)
        primary_all_not_found = (
            bool(primary_target_results)
            and all(r.classification == Classification.NOT_FOUND for r in primary_target_results)
        )
        all_not_found = bool(target_results) and all(
            r.classification == Classification.NOT_FOUND for r in target_results
        )
        if all_not_found or primary_all_not_found:
            verdict_parts.append("TARGET_NOT_FOUND")
            notes.append(
                "baseline(도메인 루트) 은 OK 인데 입력 URL 의 모든 진입 시도가 404 — "
                "사이트 차단이 아니라 그 URL 의 글이 존재하지 않음 (잘못된 URL 또는 삭제됨)."
            )
        elif target_results and all(r.classification == Classification.BLOCKED_BOT for r in target_results):
            verdict_parts.append("ENTRY_BLOCKED")
            notes.append(
                "baseline(도메인 루트) 은 OK 이지만 입력 URL 의 모든 진입 시도가 봇 보호로 차단됨 — "
                "사이트 전체 차단보다 특정 경로/엔트리 보호에 가까움."
            )

    verdict = " / ".join(verdict_parts) if verdict_parts else "분류 보류"

    return Diagnosis(
        slug=slug,
        url=url,
        verdict=verdict,
        recommended_strategy=recommended_strategy,
        recommended_headers_summary=recommended_headers_summary,
        recommended_polling_interval_sec=interval,
        list_candidates_summary=list_summary,
        article_entry_ok=article_ok,
        notes=notes,
    )
