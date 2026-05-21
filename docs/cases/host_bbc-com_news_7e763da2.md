---
slug: host_bbc-com_news_7e763da2
url: https://www.bbc.com/news
status: ✅ 자동 등록 회복 (preflight b-hit, baseline 8건) — prompt §8a 룰 추가 (carousel dedup + iso slash) 후.
outcome: registered
date: 2026-05-19
fix_layer:
failure_keys: [post_id_unique, carousel_dedup, narrow_wide_no_sweet_spot]
config_strategy:
adapters_changed:
engine_files_touched:
tags: [arxiv-2601-bench, western-news, carousel-reuse, data-indexcard]
requested_by: 운영자 (prior-art followup — arxiv-2601-bench 11 사이트 자동 등록 측정)
vocab_candidates:
  - candidate: carousel_dedup_required
    confidence: high
    evidence:
      - experiments/arxiv-2601-bench/bot_results.md §6 (BBC — attempt 1 dup 1건, attempt 2 narrow 0건, attempt 3 wide+`a[href]` dup 1건)
    reasoning: "BBC News 메인 = `data-indexcard=true` 카드 가 main + featured/companion 두 zone 에 같은 글 노출. attempt 2 = config_writer 가 narrow 시도 (analytics group position 1 으로) → fail (0건, 해당 zone 이 정적 fetch 시 빈 placeholder). attempt 1/3 = wide → dup. **narrow 와 wide 사이 working 구역 없음** — section 별 zone 이름이 안정적이지 않거나 정적 응답에 일부 zone 만 박힘. [[host_edition-cnn-com_root_82356c05]] 와 같은 후보 — 카운트 high=2."
    analysis_date: 2026-05-19
    deferred: true
---

## 무엇이 일어났나

`/watch https://www.bbc.com/news` (arxiv-2601-bench #6). probe→generate 3 attempts 모두 실패.

attempts:
- attempt 1: `httpx_html` + `div[data-indexcard="true"]` → `post_id_unique` 중복 1건
- attempt 2: `httpx_html` + `section[data-analytics-group="true"][data-analytics_group_position="1"] div[data-indexcard="true"]` → posts_nonempty 0건 (zone 1 정적 응답에 없음)
- attempt 3: `httpx_html` + `main article div[data-indexcard="true"] a[href]` → 중복 1건

## 왜

BBC News 메인 페이지 구조:
- 정적 응답 = main feature + 4-5 companion card 즉시 박힘
- featured zone 의 톱 카드가 main feature 와 *같은 글* 중복 노출
- attempt 2 가 analytics group position=1 으로 narrow 시도 → 정적 응답에 해당 attribute 없는 zone

→ wide row_selector = 중복 1건, narrow 시도 = 0건. 중간 영역 없음.

## 픽스

**현재 없음** — Action C (config_writer.system.txt 의 carousel 가드) trigger 의 두 번째 evidence.

수동 config 가능 경로 = `data-indexcard` 카드 중 가장 *먼저* 등장한 글의 URL 만 unique 보존 후
나머지 dedup. closed vocab 의 `unique_post_id` 룰을 schema 차원에서 enforce — selector level
보다 post_id level dedup 이 robust. 단 이건 *vocab 확장 필요* (현 schema 는 dedup 옵션 없음).

대안: `row_required_selector: ":has(time)"` 또는 `:has(div.gs-c-promo-summary)` (요약 텍스트 있는
real article 만) — 같은 글의 sidebar repeat 는 보통 요약 없음. 미시도.

## bench evidence

[`experiments/arxiv-2601-bench/bot_results.md`](../../experiments/arxiv-2601-bench/bot_results.md)
§6. [[host_edition-cnn-com_root_82356c05]] 와 평행 (carousel reuse).

## preflight 결과 (2026-05-19, SKILL.md §0b 적용)

본 case 가 [[infra_handconfig_preflight_reuse_probe_2026-05-19]] 의 첫 적용 데이터.

`register.py "https://www.bbc.com/news"`:
- attempt 1: FAIL — `post_id_unique 중복 1건`, `published_at_iso 파싱 실패: ['3 hrs ago', '13 mins ago', '8 hrs ago']`
- attempt 2: **PASS** — baseline 8건 등록 ✅

prompt 의 carousel dedup 룰 (전 turn Action C) 이 attempt 1→2 회복에 기여 — LLM 이 retry 에서 narrow row_selector + ISO 가드 적용. *prompt 변경 효과 직접 실증*.

→ `carousel_dedup_required` vocab_candidate = high evidence 2건 (CNN + BBC) 그대로 유지. BBC 등록 성공으로 BBC 만 임계 카운트 떨어지지 X — *prompt 변경이 BBC 의 carousel 잡았다는 증명* 이라 [[host_edition-cnn-com_root_82356c05]] 와 함께 evidence 보존.

## 자가 점검 (5-질문)

1. **어느 자리?** — evidence-only. Action C 의 prompt 개선 trigger.
2. **이전 케이스 있나?** — CNN ([[host_edition-cnn-com_root_82356c05]]) 와 같은 패턴.
3. **재발 방지?** — `carousel_dedup_required` high=2 누적 (CNN + BBC).
4. **자가 의심?** — bench 1회. BBC layout 변동성 있음.
5. **회귀 검증?** — fix 미배포.
