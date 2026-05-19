---
slug: host_edition-cnn-com_root_82356c05
url: https://edition.cnn.com/
status: ❌ 자동 등록 실패 (carousel 재사용 + iso8601 mash). 손 config 또는 prompt 개선 대기.
outcome: failed
date: 2026-05-19
fix_layer:
failure_keys: [post_id_unique, title_nonempty, published_at_iso, carousel_dedup, tile_card_iso_parse]
config_strategy:
adapters_changed:
engine_files_touched:
tags: [arxiv-2601-bench, western-news, carousel-reuse, spa-light, iso-slash-date]
requested_by: 운영자 (prior-art followup — arxiv-2601-bench 11 사이트 자동 등록 측정)
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
