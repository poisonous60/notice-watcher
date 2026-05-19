---
slug: host_edition-cnn-com_root_82356c05
url: https://edition.cnn.com/
status: 🚫 거부 (CNN root 도메인 마케팅 랜딩 — board 아님. 카테고리/섹션 URL 권장) — root_marketing_homepage 게이트 (C+F+A)
outcome: rejected_with_policy
date: 2026-05-19
fix_layer: C
failure_keys: [post_id_unique, title_nonempty, published_at_iso, matches_probe_first_article, root_marketing_homepage]
config_strategy: none
adapters_changed: []
engine_files_touched: [probe/extract.py, probe/_contract.py, scripts/register.py, scripts/probe.py, prompts/config_writer.system.txt, bot/fail_taxonomy.py]
tags: [cnn, root-marketing-homepage, mixed-media-root, gate-reject, policy-reject, infra-root-gate, arxiv-2601-bench, carousel-reuse]
requested_by: poi23619
vocab_candidates:
  - candidate: carousel_dedup_required
    confidence: high
    evidence:
      - experiments/arxiv-2601-bench/bot_results.md §5 (CNN — attempt 3 post_id_unique 중복 3건)
      - experiments/arxiv-2601-bench/bot_results.md §6 (BBC — 같은 패턴 attempt 1/3 dup 1건, attempt 2 narrow 시 0건 = sweet spot 없음)
    reasoning: "carousel/grid 사이트는 같은 글이 hero/sidebar/related 등 multiple `<li class=card>` 컨테이너에 반복 → row_selector 가 그 셋을 모두 잡아 post_id_unique fail. config_writer prompt 가 `narrow` 와 `wide` 사이 sweet spot 못 찾음 (BBC = narrow 0건 / wide dup). closed vocab 의 `row_required_selector` + `exclude_selector` 로 표현 가능하나 prompt 가 carousel 인지 *명시 신호 X* — probe digest 의 `repeating_patterns` 가 같은 selector 의 중복 article URL 비율 측정 가치. 또는 prompt 에 `unique_post_id_dedup_window` 룰 직접 박는 게 간단."
    analysis_date: 2026-05-19
    deferred: true
  - candidate: tile_card_iso_parse
    confidence: med
    evidence:
      - experiments/arxiv-2601-bench/bot_results.md §5 (CNN — published_at_iso 파싱 실패 `2026/05/18T00:00:00+09:00`)
    reasoning: "CNN 의 카드 `data-published` 또는 `time` 요소 값이 `YYYY/MM/DDT...` (slash-date + ISO time mash). 현 transform `iso8601` 의 default 포맷 list 가 slash 구분자 안 잡음. `[\"iso8601\", [\"%Y/%m/%dT%H:%M:%S%z\"]]` 명시하면 해결 가능 — 별 vocab 확장 X (기존 transform 의 args 확장). prompt 에 slash-date 예시 추가하는 정도가 ROI 가장 큼."
    analysis_date: 2026-05-19
    deferred: true
---

## 무엇이 일어났나

`/watch https://edition.cnn.com/` (arxiv-2601-bench 11 사이트 중 5번째). probe→generate
파이프라인이 3 attempts 모두 실패. 사용자 메시지에 "손어댑터 필요" 안내 박힘.

attempts:
- attempt 1: `httpx_html` + `li.card[data-open-link]` → posts_nonempty 0건 (정적 fetch 시 카드 없음 — SPA 렌더)
- attempt 2: `httpx_html` + 매우 긴 utility class 체인 (`ul.container__field-links.container_vertical-shelf-carousel__...`) → posts_nonempty 0건 (마찬가지)
- attempt 3: `playwright_html` + `ul.container__field-links > li.card[data-open-link]` → 3종 fail:
  - `post_id_unique` 중복 3건
  - `title_nonempty` 빈 글 — `cnni-fast`, `they-sold-their-home-in-colorado-to-live-on-a-sailboat` 등
  - `published_at_iso` 파싱 실패 — `2026/05/18T00:00:00+09:00`, `2026/05/17T00:00:00+09:00`

## 왜

CNN edition 메인페이지 = 한 글이 multiple carousel 컨테이너에 노출:
1. hero section
2. `container_vertical-shelf-carousel__selected` (오른쪽 추천)
3. `container_lead-plus-headlines__field-links` (sub-feature)

같은 `data-open-link` URL 이 2-3 곳에 박혀 row_selector 가 모두 잡으면 post_id 중복.

`cnni-fast` = CNN International live ticker 카드 — 글 아님, title 없음 (제목 자리에 live 표시
구성요소). 같은 row_selector 로 잡혀 빈 title 생성.

`2026/05/18T00:00:00+09:00` = CNN 의 카드 metadata 값. ISO 8601 형식 아님 (slash 가 표준 위반).
현 transform default 포맷이 dash-date 우선이라 파싱 실패.

## 픽스

**현재 없음** — 본 case 는 evidence-only. fix 후보:

### prompt 개선 (Action C — config_writer.system.txt)

1. carousel 가드: `같은 post_id 가 다른 row 에 반복되면 row_selector 가 너무 wide — narrow
   container 한정. unique 강제`
2. iso8601 slash-date: `published_at 값이 YYYY/MM/DDT 형식이면 transform [["iso8601",
   ["%Y/%m/%dT%H:%M:%S%z"]]] 추가`

### 손-config (대체 경로)

playwright_html + `section[data-zone-label="zone-1"] li.card[data-open-link]` (main zone 1만) +
`exclude_selector` 로 cnni-fast 제외 + `iso8601` transform. 단 *prompt 개선이 다른 carousel
사이트에도 영향* → C 우선.

## bench evidence

[`experiments/arxiv-2601-bench/bot_results.md`](../../experiments/arxiv-2601-bench/bot_results.md)
§5. 같은 fail key (`post_id_unique` 중복) BBC ([[host_bbc-com_news_7e763da2]]) 와 평행.

## 갱신 (2026-05-19 turn 2) — root_marketing_homepage 영구 게이트로 거부

기존 §"왜" / §"픽스" 의 carousel-dedup + iso-slash-date 진단은 *board 진입 가정* 하의 분석. 본 turn 에서 **CNN root 도메인 자체가 board 정의 X** 를 인정하고 [[infra_root_marketing_homepage_gate_2026-05-19]] 영구 게이트 박음:

- probe `list_candidates.root_marketing_homepage` 휴리스틱 (path='/' + nav/footer/dropdown/carousel/swiper 키워드 ≥ 2 + same-host article rows ≤ 15). CNN 신호: `marketing_hits=4 total_same_host=8 body_empty_likely=False`
- `scripts/register.py:_root_marketing_homepage_check` 게이트 (LLM 호출 *전* fail-fast)
- `.REJECTED.json` 마커 + `learn=False` (root 만 차단 — `/world/`, `/business/` 등 카테고리 path 는 진짜 board 가능성)
- 사용자에 안내: `카테고리/섹션 URL 시도 권장 — 예: https://edition.cnn.com/2026/`
  - ⚠ 권장 URL 의 첫 segment 가 date (`/2026/`) — 미래 개선 후보: first_article_url path 중 *워드 segment* (예: `world`) 우선 추출. case `infra_root_marketing_homepage_gate_2026-05-19` 의 deferred 후보로 기록.

기존 vocab_candidates (`carousel_dedup_required`, `tile_card_iso_parse`) 는 *root 아닌 carousel/news 사이트* (BBC root 도 root_marketing_homepage 게이트가 잡을 가능성) 에 여전히 deferred — root 게이트는 그 vocab 후보들의 *우회 경로*. 미래 카테고리 URL 등록 시도 시 fail 패턴 누적되면 다시 활성화.

## preflight 결과 (2026-05-19, SKILL.md §0b 적용)

[[infra_handconfig_preflight_reuse_probe_2026-05-19]] 의 (b) 검사. `register.py "https://edition.cnn.com/"` 결과:
- attempt 1: FAIL — `posts_nonempty: 0건` (정적 fetch 시 카드 없음)
- attempt 2: FAIL — 동일
- attempt 3 (playwright_html): FAIL — `posts_nonempty: 0건`

prompt §8a 룰 추가 *후에도 자동 등록 X*. 이유 = CNN edition 메인 = 정적 fetch 시 카드 anchor 없음 (SPA 무한 carousel). playwright 시도도 wait_selector 부정확 → 0건. prompt 룰만으론 한계 — strategy 자체 또는 inline_js_data_candidates (probe digest 의 다른 후보, 4건) 활용 필요.

→ **§2 진입 대상**. *손-config 작성 = 다음 batch* (본 turn scope = preflight 적용 + §0b 박기). 진단 진입 시 트랙 B 후보: 2c (probe heuristic — `inline_js_data_candidates` 자동 활용) 또는 vocab `carousel_dedup_required` 임계 도달 가속 (high=2, 1건 더 필요).

## 자가 점검 (5-질문)

1. **어느 자리?** — evidence-only case (fix_layer 없음). Action C (prompt 개선) 의 trigger 가 됨.
2. **이전 케이스 있나?** — 같은 host CNN 없음. `post_id_unique` 중복 fail 한 cases 다수 (humblebundle
   등) 이나 그건 *dynamic id selector* 원인 — carousel reuse 와 카테고리 다름.
3. **재발 방지?** — `carousel_dedup_required` vocab_candidate 누적. 현재 high=2 (CNN + BBC). ADR 0003
   임계 `high≥1 + total≥3` 까지 1건 더 필요.
4. **자가 의심?** — bench 1회. CNN edition 메인은 layout 자주 바뀜 — 다음 재-등록 시 같은 fail 재현 보장 X.
5. **회귀 검증?** — fix 미배포 (evidence only). prompt 개선 후 같은 URL 재-시도 시 회복 측정.
