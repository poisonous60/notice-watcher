"""bot.fail_taxonomy.classify_fail — rc + tail 조합별 (kind, subkind) 검증.

각 케이스: 실제 register.py / worker.py 가 찍는 print 라인 fixture 로 분류 결과 확인.

`CASES` module 변수는 `(name, args, expect_kind, expect_sub)` 튜플 리스트 — completeness test
(`test_catalog_completeness.py`) 가 import 해서 catalog 의 모든 fixed Subkind 가 fixture 에 등장하는지 검증.
"""
from __future__ import annotations

from typing import Optional


# 실제 register.py / worker.py 가 찍는 print 라인 fixture.
# 형식: (name, (status, rc, tail), expect_kind, expect_sub).
_GEN_FAIL_BODY = """[PHASE] generate max=4
[register] gemini 생성+검증 (모델=gemini-2.5-flash, 최대 4회):
... attempt 1: [FAIL] posts_nonempty: 0건
... attempt 2: [FAIL] article_body_len: post_id=42 0자 (<100 — content selector 의심)
[register] ❌ 자동 처리 불가. → /opt/.../foo.FAILED.json
  마지막 실패 사유:
[FAIL] article_body_len: post_id=42 0자 (<100 — content selector 의심)"""


CASES: list[tuple[str, tuple[Optional[str], Optional[int], Optional[str]], str, Optional[str]]] = [
    # 1차 (rc 단독) ----
    ("status=pending", ("pending", None, None), "pending", None),
    ("status=running", ("running", None, None), "running", None),
    ("status=done_rc0", ("done", 0, ""), "done", None),
    ("status=none_rc0", (None, 0, ""), "done", None),

    # bug (rc 음수) ----
    ("bug_-1", ("failed", -1, "chromium 락 대기 초과: ..."), "bug", "chromium_lock_timeout"),
    ("bug_-2", ("failed", -2, "register.py 실행 시간 초과 (600s)"), "bug", "subprocess_timeout"),
    ("bug_-3", ("failed", -3, "register.py 실행 중 예외: RuntimeError(...)"), "bug", "subprocess_exception"),
    ("bug_-5", ("failed", -5, "(BUG: 재시작 2회로 한도 2 도달)"), "bug", "attempts_limit"),
    ("bug_-99", ("failed", -99, "worker exception: KeyError(...)"), "bug", "worker_exception"),

    # worker race: status='failed' AND rc=0 ----
    ("race_failed_rc0", ("failed", 0, ""), "bug", "registered_but_no_state"),

    # gen_fail (rc=1) ----
    ("gen_fail_article_body_len", ("failed", 1, _GEN_FAIL_BODY), "gen_fail", "article_body_len"),
    ("gen_fail_posts_nonempty", ("failed", 1, "[FAIL] posts_nonempty: 0건"), "gen_fail", "posts_nonempty"),
    ("gen_fail_published_at_iso", ("failed", 1, "[FAIL] published_at_iso: ISO8601 파싱 실패"),
     "gen_fail", "published_at_iso"),
    ("gen_fail_post_id_stable", ("failed", 1, "[FAIL] post_id_stable_shape: ..."),
     "gen_fail", "post_id_stable_shape"),
    ("gen_fail_title_nonempty", ("failed", 1, "[FAIL] title_nonempty: ..."), "gen_fail", "title_nonempty"),
    # llm_api — API 단 실패 (429/UNAVAILABLE/네트워크). provider-agnostic. 새 split 라벨 + alias 둘 다 잡음.
    ("gen_fail_llm_api_new_split_label",
     ("failed", 1, "생성 실패: LLM 호출 실패 (gemini): 429 RESOURCE_EXHAUSTED"),
     "gen_fail", "llm_api"),
    ("gen_fail_llm_api_fallback_both_failed",
     ("failed", 1, "생성 실패: LLM 호출 실패 (fallback): codex network err; gemini 429 RESOURCE_EXHAUSTED"),
     "gen_fail", "llm_api"),
    ("gen_fail_llm_api_legacy_gemini_token",
     ("failed", 1, "생성 실패: gemini 호출/파싱 실패 (429 RESOURCE_EXHAUSTED)"),
     "gen_fail", "llm_api"),
    ("gen_fail_llm_api_unavailable",
     ("failed", 1, "Gemini API 503: UNAVAILABLE"),
     "gen_fail", "llm_api"),
    # llm_parse — 응답 JSON 깨짐. 처방 다름 (prompt schema / 모델 강화). codex 큰 응답에서 다발 (2026-05-24).
    # split 후 라벨 = "LLM 응답 JSON 파싱 실패 (codex)" — provider 가 실제 응답 준 쪽 (FallbackClient 도 정확).
    ("gen_fail_llm_parse_new_split_label_codex",
     ("failed", 1,
      "(직전 시도 생성 실패: LLM 응답 JSON 파싱 실패 (codex): 모델 응답을 JSON 으로 파싱 실패: "
      "Expecting ',' delimiter: line 1 column 2556 (char 2555)"),
     "gen_fail", "llm_parse"),
    ("gen_fail_llm_parse_legacy_gemini_label",
     ("failed", 1,
      "생성 실패: gemini 호출/파싱 실패: 모델 응답을 JSON 으로 파싱 실패: Expecting value"),
     "gen_fail", "llm_parse"),
    # 구 코드 동작: [FAIL] 라인이 있으면 그 이름 그대로 (LLM 토큰 무시). dynamic passthrough 가
    # llm_* 매처 *앞* 에 와야 보존됨 — 회귀 차단용 fixture.
    ("gen_fail_unknown_fail_beats_llm_token",
     ("failed", 1, "[FAIL] foo_bar_baz: 어쩌고 ... RESOURCE_EXHAUSTED ..."),
     "gen_fail", "foo_bar_baz"),
    ("gen_fail_no_match", ("failed", 1, "something else"), "gen_fail", None),

    # policy_reject (rc=2) ----
    ("policy_login", ("failed", 2, "[register] LOGIN_REQUIRED (네이버카페 비공개)"),
     "policy_reject", "login_required"),
    ("policy_blocked_bot", ("failed", 2, "[register] BLOCKED_BOT"), "policy_reject", "blocked_bot"),
    ("policy_blocked_ip", ("failed", 2, "[register] BLOCKED_IP"), "policy_reject", "blocked_ip"),
    ("policy_blocked_geo", ("failed", 2, "[register] BLOCKED_GEO"), "policy_reject", "blocked_geo"),
    ("policy_no_match", ("failed", 2, "[register] something"), "policy_reject", None),

    # url_dead (rc=4 = 새 runs / rc=2 + tail token = 옛 entries re-classify) ----
    ("url_dead_target_rc4",
     ("failed", 4, "[register] 입력 URL 의 글이 존재하지 않음 — 모든 진입 시도가 HTTP 404 (verdict='TARGET_NOT_FOUND')."),
     "url_dead", "target_not_found"),
    ("url_dead_cert_rc4",
     ("failed", 4, "[register] 목록 페이지 접근 단계 이전에 SSL 인증서/DNS 가 깨짐 (verdict='CERT_OR_DNS_BROKEN')."),
     "url_dead", "cert_or_dns_broken"),
    ("url_dead_soft_404_rc4",
     ("failed", 4, "[register] 입력 URL 이 HTTP 200 으로 응답하지만 not-found shell 로 보임 (title: Not Found) (verdict='SOFT_404')."),
     "url_dead", "soft_404"),
    ("url_dead_target_rc2_legacy",
     ("failed", 2, "[register] 입력 URL 의 글이 존재하지 않음 (verdict='TARGET_NOT_FOUND'). 게시판 목록 URL 또는 다른 글 URL 로 재시도."),
     "url_dead", "target_not_found"),
    ("url_dead_cert_rc2_legacy",
     ("failed", 2, "[register] 목록 페이지 접근 단계 이전에 SSL 인증서/DNS 가 깨짐 (verdict='CERT_OR_DNS_BROKEN')."),
     "url_dead", "cert_or_dns_broken"),

    # capability_blocked (rc=5) — anti-bot/captcha 차단 = 능력 부족 (2026-05-21 policy_reject split) ----
    ("cap_cloudflare",
     ("failed", 5, "[register] 목록 페이지에 정적으로도 headless 로도 접근 실패 (verdict='CLOUDFLARE_PROTECTED_SITE'). anti-bot/captcha 차단 — 능력 부족(정책 아님)."),
     "capability_blocked", "cloudflare"),
    ("cap_baseline_blocked",
     ("failed", 5, "[register] 목록 페이지에 정적으로도 headless 로도 접근 실패 (verdict='BASELINE_BLOCKED'). anti-bot/captcha 차단 — 능력 부족(정책 아님)."),
     "capability_blocked", "baseline_blocked"),
    ("cap_entry_blocked_unclassified",
     ("failed", 5, "[register] 목록 페이지에 정적으로도 headless 로도 접근 실패 (verdict='분류 보류'). anti-bot/captcha 차단 — 능력 부족(정책 아님)."),
     "capability_blocked", "entry_blocked"),
    ("cap_probe_memory_guard",
     ("failed", 5, "[register] ❌ 등록 불가 — probe memory guard. [BLOCKED] probe_memory_guard — heavy SPA OOM blower (probe.py:_start_memory_guard self-kill rc=99). root-cause: tracemalloc 조사 별도."),
     "capability_blocked", "probe_memory_guard"),
    ("cap_http_403",
     ("failed", 5, "[register] ❌ 자동 처리 불가 — 4xx capability_blocked. HTTPStatusError: Client error '403 Forbidden' for url 'https://www.bloomberg.com/podcasts'"),
     "capability_blocked", "http_4xx_blocked"),
    ("cap_http_451",
     ("failed", 5, "HTTPStatusError: Client error '451 Unavailable For Legal Reasons' for url 'https://example.com/feed'"),
     "capability_blocked", "http_4xx_blocked"),
    ("cap_http_429",
     ("failed", 5, "HTTPStatusError: Client error '429 Too Many Requests' for url 'https://example.com/feed'"),
     "capability_blocked", "http_4xx_blocked"),

    # gate_reject (rc=3) ----
    ("gate_recognizer",
     ("failed", 3, "[PHASE] recognize_reject (wikipedia_article)\n[register] ❌ 등록 거부 — ..."),
     "gate_reject", "recognizer:wikipedia_article"),
    ("gate_nav_only",
     ("failed", 3, "[register] ❌ 등록 거부 — 단일 article (nav-only same-host)."),
     "gate_reject", "nav_only"),
    ("gate_meta_diverging",
     ("failed", 3, "[register] ❌ 등록 거부 — 단일 article (meta 선언 + 발산 first_article)."),
     "gate_reject", "meta_diverging"),
    ("gate_multi_host_hub",
     ("failed", 3, "[register] ❌ 등록 거부 — multi-host hub root."),
     "gate_reject", "multi_host_hub"),
    ("gate_root_marketing_homepage",
     ("failed", 3, "[register] root 도메인 마케팅 랜딩/허브 페이지 같음 — 글 행 반복 패턴 자리에 nav/footer/dropdown/carousel/swiper 메뉴가 우세하고, 같은 호스트로 가는 article rows 가 작음.\n[register] ❌ 등록 거부 — root 도메인 마케팅 랜딩/허브."),
     "gate_reject", "root_marketing_homepage"),
    ("gate_board_shape",
     ("failed", 3, "[register] ❌ 등록 거부 — 게시판 형식 아님."),
     "gate_reject", "board_shape"),
    ("gate_classifier_catalog",
     ("failed", 3, "accept_path catalog 거부 (게이트 통과 + 분류기 catalog) [classifier=catalog conf=0.98: 패키지 레지스트리]"),
     "gate_reject", "classifier_reject"),
    ("gate_classifier_content",
     ("failed", 3, "accept_path content 거부 (게이트 통과 + 분류기 content) [classifier=content conf=0.9: 단일 글]"),
     "gate_reject", "classifier_reject"),
    ("gate_no_match", ("failed", 3, "something"), "gate_reject", None),

    # unknown rc ----
    ("unknown_rc99", ("failed", 99, "weird"), "unknown", None),
]


def run() -> list[tuple[str, bool, str]]:
    from bot.fail_taxonomy import classify_fail
    cases: list[tuple[str, bool, str]] = []

    for name, args, expect_kind, expect_sub in CASES:
        kind, sub, reason = classify_fail(*args)
        ok = (kind == expect_kind) and (sub == expect_sub)
        cases.append((name, ok, f"got=({kind!r},{sub!r}) expect=({expect_kind!r},{expect_sub!r})"))

    # reason_short 추출 — fixture 형식이 약간 달라서 별도 검사 (CASES 안 박지 않음).
    kind, sub, reason = classify_fail("failed", 1, "line1\nline2\n\n  \n[FAIL] x\n")
    cases.append(("reason_picks_last_nonblank", reason == "[FAIL] x", f"reason={reason!r}"))

    kind, sub, reason = classify_fail("failed", 1, None)
    cases.append(("reason_none_on_empty_tail", reason is None, f"reason={reason!r}"))

    long_tail = "x" * 500
    kind, sub, reason = classify_fail("failed", 1, long_tail)
    cases.append(("reason_caps_200", reason is not None and len(reason) == 200,
                  f"len={len(reason) if reason else None}"))

    return cases


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    results = run()
    failed = [(n, d) for n, ok, d in results if not ok]
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {d}")
    if failed:
        print(f"\n{len(failed)} FAILED")
        sys.exit(1)
    print(f"\n{len(results)} passed")
