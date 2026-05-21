---
slug: host_nationalgeograp_root_2be4a852
url: https://www.nationalgeographic.com/
status: 🚫 거부 (NatGeo root 도메인 마케팅 랜딩 — board 아님. 카테고리/섹션 URL 권장) — root_marketing_homepage 게이트 (C+F+A)
outcome: rejected_with_policy
date: 2026-05-19
fix_layer: C
failure_keys: [post_id_stable_shape, title_nonempty, article_body_len, row_type_mix, matches_probe_first_article, root_marketing_homepage]
config_strategy: none
adapters_changed: []
engine_files_touched: [probe/extract.py, probe/_contract.py, scripts/register.py, scripts/probe.py, prompts/config_writer.system.txt, bot/fail_taxonomy.py]
tags: [natgeo, root-marketing-homepage, mixed-media-root, carousel, gate-reject, policy-reject, infra-root-gate, arxiv-2601-bench]
requested_by: poi23619
vocab_candidates:
  - candidate: row_type_filter_required
    confidence: high
    evidence:
      - experiments/arxiv-2601-bench/bot_results.md §9 (NatGeo — row_selector 가 `article/...`, `tv/show/<uuid>`, `tv/movies-and-special/...`, `photography/article/...` 카드 동시 잡음)
    reasoning: "NatGeo 홈페이지 = 글(article), 비디오(tv/show), 영화 special(tv/movies-and-special) 카드 mix grid. row_selector 가 모두 잡으면 일부 row 는 글 아니라 title/published_at 없음. closed vocab 의 `row_required_selector` 또는 sample_url regex match (예: `^/(?:photography|science|environment|history|travel)/article/`) 로 *글만* 필터 가능 — 단 prompt 가 이 필터 *명시적으로 박을 신호* 없음. probe digest 의 `repeating_patterns[].sample_url` 들이 multi-type 일 때 prompt 에 `row 종류별 path prefix 다르면 글 path 만 row_required_selector 매칭` 룰 추가 가치. 또는 schema 차원의 `row_url_match` (현재 fields 의 source match 만 있고 row level 없음) 어휘 확장."
    analysis_date: 2026-05-19
    deferred: true
  - candidate: unstable_post_id
    confidence: low
    evidence:
      - "experiments/arxiv-2601-bench/bot_results.md §9 (post_id_stable_shape: `science/article/heat-training-benefits-risks-exercise-hot-...` — slug 가 매우 길고 가변)"
    reasoning: "slug-based post_id 가 길어지면 stable_shape 검증이 fail. 단 NatGeo 같은 사이트 = slug 가 *실제로 안정* (URL 영구). 검증 룰이 over-strict 한 가능성 — 별 점검 가치. probe baseline classifier 의 stable_shape 임계 완화 검토."
    analysis_date: 2026-05-19
    deferred: true
---

## 갱신 (2026-05-19 turn 2) — root_marketing_homepage 영구 게이트로 거부

기존 §"왜" / §"픽스" 의 row-type-mix 진단은 *board 진입 가정* 분석. 본 turn 에서 **NatGeo root = magazine + video hub = board 정의 X** 를 인정하고 [[infra_root_marketing_homepage_gate_2026-05-19]] 영구 게이트 박음:

- probe `list_candidates.root_marketing_homepage` 휴리스틱 매칭. NatGeo 신호: `marketing_hits=4 total_same_host=4 body_empty_likely=False`. top selectors: `SwiperWrapper > TileStackCarousel__Card`, `Swiper__DotContainer__Dot`, `Carousel__Inner > li.CarouselSlide`, `GlobalFooter__Menu__List__Item`
- `.REJECTED.json` 마커 + `learn=False`
- 사용자에 안내: `카테고리/섹션 URL 시도 권장 — 예: https://www.nationalgeographic.com/tv/` (probe first_article=`/tv/show/<uuid>` 이라 `/tv/` segment 추출. 더 유의미한 권장은 `/science/`, `/history/`, `/photography/` 카테고리 — 미래 first_article path 의 *비-단일-segment* 권장 후보 휴리스틱 개선 여지)

기존 vocab_candidates (`row_type_filter_required`, `slug_stable_shape_relaxation`) 는 *root 아닌 카테고리 URL* (예: `/science/`) 등록 시도 시 다시 활성화. root 게이트는 우회 경로.

## 무엇이 일어났나

`/watch https://www.nationalgeographic.com/` (arxiv-2601-bench #9). 3 attempts 모두 실패.

attempts (3 모두 비슷):
- row_selector = `div.HomepagePromos__promo, article.PromoTile, li.CarouselSlide, div.TileStackCarousel__Card`
- fails:
  - `article_body_len: post_id=photography/article/how-to-capture-the-cosmos-with-your-phone 0자` (body 검증)
  - `post_id_stable_shape: 안정적 ID 모양 아님(공백 등): ['science/article/heat-training-benefits-risks-exercise-hot-...']`
  - `title_nonempty: title 빈 글: ['tv/show/94ad3635-e9e4-4d86-923d-bbfdf6f4ef6b', 'tv/movies-and-special/...']`

## 왜

NatGeo 홈페이지 = magazine + video hub. card type 4종 mix:
1. `article` (글) — path `/<topic>/article/<slug>` (글 본문 OK)
2. `tv/show/<uuid>` (비디오 시리즈) — 카드에 title 박힘 X (poster image only)
3. `tv/movies-and-special/<slug>` (영화) — 마찬가지
4. `photography/article/<slug>` (포토 essay) — 정적 fetch 시 body 0자 가능 (lightbox 렌더)

row_selector 가 4종 모두 잡아 *type 2/3 카드의 title 빈* + *type 4 카드의 body 0자* 검증 실패.

또 `post_id_stable_shape` = slug 가 80+ 자라 stable_shape 휴리스틱이 *공백 추정* (실제로는 공백
없고 dash 만 — 휴리스틱 false positive).

## 픽스

**현재 없음**. 두 갈래:

### 갈래 1: prompt 개선 (Action C)

`row_url_match` 어휘 또는 prompt 룰: "row 의 href 가 multi-type 이면 글 path prefix 만 매칭하는
`row_required_selector` 또는 fields 의 source match 추가" — 단 현 vocab 에 row-level url match 없음.
임시로 fields.url.source 에 match regex 박고 None 이면 row skip 되는 효과 활용.

### 갈래 2: 수동 config

`row_required_selector: "a[href*='/article/']"` 추가 + `exclude_selector: ".TileStackCarousel__Card"`
(영상/special hub) — type 1+4 만 통과. 단 type 4 의 body 0자 문제는 `body_empty_acceptable: true`
또는 article.fetch_kind 변경 별 필요.

### stable_shape 검증 완화

별 evidence 누적되면 probe 휴리스틱 임계 조정. 단일 NatGeo 만으론 부족.

## bench evidence

[`experiments/arxiv-2601-bench/bot_results.md`](../../experiments/arxiv-2601-bench/bot_results.md)
§9.

## preflight 결과 (2026-05-19, SKILL.md §0b 적용)

[[infra_handconfig_preflight_reuse_probe_2026-05-19]] 의 (b) 검사. `register.py "https://www.nationalgeographic.com/"` 결과:
- attempt 1: FAIL — `article_body_len: post_id=how-to-capture-the-cosmos-with-your-phone 0자`, `post_id_unique 중복 1건`
- attempt 2: FAIL — body_len 0자 동일
- attempt 3: FAIL — `post_id_unique 중복 3건`

prompt §8a 룰 (row_type_mix 가드 + carousel dedup) *적용 후에도 자동 등록 X*. probe first_article_url 자체가 single article 인 photography URL → body 0자. row_selector 가 type mix 안 잡음 (`row_required_selector: a[href*='/article/']` 권고 prompt 룰 안 박혔거나 LLM 이 무시).

→ **§2 진입 대상**. 다음 batch 수동 config — narrow row_selector + body_empty_acceptable 또는 article.fetch_kind 변경.

## 자가 점검 (5-질문)

1. **어느 자리?** — evidence-only. `row_type_filter_required` vocab-ext trigger 의 첫 high evidence.
2. **이전 케이스 있나?** — [[host_itch-io_game-assets_2596d376]] (dynamic id selector — 다른 카테고리).
   [[host_humblebundle-co_software_4589b229]] = cross-section tile pattern (비슷한 multi-type mix).
3. **재발 방지?** — vocab 확장 또는 prompt 룰 추가 시 비슷한 multi-type 사이트 자동 처리 가능.
4. **자가 의심?** — bench 1회. NatGeo layout 비교적 안정 (메이저 사이트).
5. **회귀 검증?** — fix 미배포.
