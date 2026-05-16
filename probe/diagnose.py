"""Phase 10: verdict + 권장 어댑터 방식."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .baseline import is_baseline_blocked
from .types import Classification, Diagnosis, Result


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
    if baseline_bot_only:
        notes.append("baseline 도메인 루트도 봇 보호(Cloudflare 등)로 막힘 — 사이트 자체 정책, IP 차단은 아님")
    elif not baseline_ok:
        notes.append("baseline ping 일부 실패 — IP/도메인 차단 의심")

    # 가장 약한 통과 결정
    static_ok = [r for r in static_results if r.classification == Classification.OK]
    headless_ok = headless is not None and headless.classification == Classification.OK
    captured_ok = captured_retry is not None and captured_retry.classification == Classification.OK

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
            payload = json.loads(list_candidates_path.read_text(encoding="utf-8"))
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
    if baseline_bot_only:
        verdict_parts.append("CLOUDFLARE_PROTECTED_SITE")
    elif not baseline_ok:
        verdict_parts.append("BASELINE_BLOCKED")
    if static_ok and not any("Cloudflare" in n for r in static_results for n in r.notable):
        verdict_parts.append("정적 HTTP로 충분")
    elif captured_ok:
        verdict_parts.append("캡처 헤더 주입 시 정적 가능")
    elif headless_ok:
        verdict_parts.append("JS 실행 필요 (Cloudflare 등)")

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
