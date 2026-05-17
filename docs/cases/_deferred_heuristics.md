# 보류한 휴리스틱 일반화 후보

case 처리 중 떠올랐으나 *지금* 박지 않은 probe/엔진 일반화 후보. 같은 패턴 1건 더 들어오면 임계량 도달 — 그때 휴리스틱화.

파일명 `_` prefix → `cases_index.py` 가 INDEX.md/DB 빌드 skip.

format: `- **<후보명>** — <신호> — 잡힐 case — 보류 사유 — 재검토 트리거 — 최초 commit`

새 후보 add: 한 줄 append. 박을 때 그 줄 삭제 + commit msg "deferred_heuristics 제거: <후보명>".

## 후보

- **[검토 완료 2026-05-17]** `_external_only_check` — 박지 않기로 결정. 신호 (`total≥1 AND ratio≥0.95`) 임계 보수화 (`total≥3`) 해도 잡히는 4 누적 케이스 (mdn/wiki-mirror/tistory/poly-pizza) 다 *이미 article_page_reject 인식기로 cover*. `total<3` 케이스 (github-wiki-see/poly-pizza) 는 호스트별 인식기 영역 (URL pattern 직접 등록) 이 정확. 휴리스틱 박는 가치 ≈ 0
- **[lifted 2026-05-17 commit `infra_multi_host_hub_reject`]** `_multi_host_hub_check` → `probe/extract.py:list_row_external_host` 의 `multi_host_hub` 필드 (≥3 unique external hosts AND ratio≥0.95) + `scripts/register.py:_multi_host_hub_check` 사전 거부 게이트. tistory root 자동 reject, poly-pizza FP 0%
- **[lifted 2026-05-17 commit `infra_pipeline_lift_round1`]** `cross_parent_aggregate_tile_pattern` → `static_vs_headless_check` rule 2 (selector-level diff) 로 박음
- **[lifted 2026-05-17 commit `infra_pipeline_lift_round1`]** `first_article_url_query_heavy_penalty` → `_article_url_score` 의 sort/filter/search/page/category query penalty 로 박음
- **[lifted 2026-05-17 commit `infra_pipeline_lift_round1`]** `cross_parent_aggregate_tile_pattern` → `static_vs_headless_check` rule 2 (selector-level diff) 로 박음
- **[lifted 2026-05-17 commit `infra_pipeline_lift_round1`]** `first_article_url_query_heavy_penalty` → `_article_url_score` 의 sort/filter/search/page/category query penalty 로 박음
