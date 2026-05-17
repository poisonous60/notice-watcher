---
slug: infra_extra_signal_hints_2026-05-17
url: (인프라 case — 특정 사이트 X. 트리거 = retry 메커니즘 진단 후 1차 prompt 강화)
status: 🏗 인프라 (probe 가 이미 잡은 신호를 LLM prompt 의 별도 hint 블록으로 강조)
outcome: improved
date: 2026-05-17
fix_layer: F
failure_keys: [retry_same_failure_loop, static_shell_ignored, body_empty_likely_buried, llm_ignores_meta_notes]
config_strategy:
adapters_changed:
engine_files_touched: [scripts/register.py]
tags: [self-improvement, escalation-hint, signal-promotion, static-vs-headless, body-empty-likely, row-interactive-action, retry-mitigation]
requested_by: 운영자 (dev box session, retry 메커니즘 진단 요청)
---

## 트리거

운영자 질문: "지금 generate retry 가 의미 없는 것 같다. 개선 가능한 부분?"

진단 (output/usage.sqlite3 + .FAILED.json 7건):
- attempt 1/2/3 prompt_tokens 변화: 125k → 126k → 127k (feedback 만 +1k, output 거의 동일)
- 1차 실패 → 2-3차 회복률 = 1/6 ≈ 17%
- max_attempts=4 default 인데 4번째 attempt 한 번도 호출 안 됨
- 같은 모델 (gpt-5.4-mini) + 거의 같은 prompt → 같은 실수 반복

Codex 리뷰 후 우선순위 1 (1차 prompt 강화) 부터 진행. retry 자체보다 "retry 안 가게" 가 ROI 큼.

핵심 발견:
- piku digest 의 `notes` 에 "정적 응답이 빈 shell — Playwright 응답이 정적보다 3.3배 크고 row-like 요소 만 잡힘. strategy=playwright_html 필수" 박혀 있음 (probe/diagnose.py 의 static_vs_headless rule 1)
- 같은 digest 의 `list_candidates.body_empty_likely=true` + `row_interactive_action.is_interactive_action=true` + matched_keyword `['월드컵', '이상형월드컵']` 박혀 있음
- 즉 **probe 가 이미 신호 다 잡았는데** LLM 이 *125k 토큰 meta JSON 안에 묻혀서 무시* — retry 3 회 다 같은 httpx_html selector 반복

기존 `_list_strategy_hint(digest)` 는 `static_ok_preset` 가 있으면 None 반환 → piku 처럼 정적 GET 200 OK 인데 빈 shell 인 케이스에 hint 안 박힘. notes 의 신호는 meta JSON 안에만.

## 픽스 (fix_layer: F — 1 파일)

### F-1. `scripts/register.py` — `_extra_signal_hints(digest)` 신규 함수

`_list_strategy_hint` 직후 호출. 두 분기:

(A) **정적 vs Playwright 신호 — notes 키워드 매치**
- `"정적 응답이 빈 shell"` → "strategy=httpx_html 0건 나옴 → playwright_html + wait_selector. 또는 inline JSON island 파싱"
- `"정적 응답 vs Playwright DOM"` → "headless 에만 mosaic/tile 다수 — 같은 row_selector 정적으로 잡으면 0건 → retry 다 실패"

(B) **`list_candidates.body_empty_likely=true` 분기**
- `row_interactive_action.is_interactive_action=true` 면 게임/투표 사이트 (sample row text + matched keyword 박음)
- `row_external_host.external_ratio` 있으면 aggregator/검색결과 (sample external urls 박음)
- 권고: `article.body_empty_acceptable: true` + content 키 비우거나 후보 1-2개만. 봇이 body_empty_at_baseline 박아 사용자 알림에 "본문 추출 안 됨" 자동 표시.

`_preflight` 의 hints 리스트에 `extend(_extra_signal_hints(digest))` 추가. build_user_prompt 의 escalation_hint 블록으로 prompt 앞쪽에 박힘. build_retry_prompt 가 build_user_prompt 의 base 재사용 → retry 도 자동 전파.

## 효과 (예상)

- **piku (이상형월드컵)** — 1차 prompt 에 명시 hint 2개 박힘:
  1. "정적 응답이 빈 shell → playwright_html 필수"
  2. "body_empty_likely=true (행 텍스트 게임/투표 패턴) → body_empty_acceptable:true"
  
  LLM 이 1회차에 SPA 인식 + body_empty 인정 → 회복 기대
- **humblebundle** — 옛 probe artifacts 라 notes 부재. **새 probe 돌리면 notes 박힘** (commit 33b01af 의 rule 2 적용 후) → 자동 회복 가능성
- **jobplanet/iln-ieee** — body_empty_likely 신호도 notes 도 없음. 이번 작업 미커버. 후속 작업 (feedback trace 풍부화 또는 추가 휴리스틱) 필요

## 검증

- `python scripts/probe_smoke.py --stage 3 --stage 5`: 312 PASS 0 FAIL (configs validate + heuristic units)
- `_extra_signal_hints` 직접 호출 (6 사이트):
  - piku: blank_shell + body_empty 둘 다 hint 박힘 ✓
  - humblebundle/jobplanet/nature/iln/arca-live: hint 0건 (false positive 0) ✓

## 한계

- humblebundle: 새 probe 재실행 필요 (옛 artifacts 라 notes 부재). 운영자 수동 trigger 또는 다음 사용자 등록 시 자동
- jobplanet/iln-ieee/theholocaust: meta 신호 없는 단일 article URL. Phase 1 (URL pattern 게이트) 또는 Phase 3 (feedback trace) 후속

## 후속 작업

- Phase 3: `generate/validate.py:feedback_text()` 풍부화 — prev cfg 의 strategy/row_selector echo + 매치 횟수 trace
- Phase 1 (옵션): `is_article_page_url` 휴리스틱 (jobplanet/iln-ieee 잡음, false positive 위험 검토 필요)
