# 보류한 휴리스틱 일반화 후보

case 처리 중 떠올랐으나 *지금* 박지 않은 probe/엔진 일반화 후보. 같은 패턴 1건 더 들어오면 임계량 도달 — 그때 휴리스틱화.

파일명 `_` prefix → `cases_index.py` 가 INDEX.md/DB 빌드 skip.

format: `- **<후보명>** — <신호> — 잡힐 case — 보류 사유 — 재검토 트리거 — 최초 commit`

새 후보 add: 한 줄 append. 박을 때 그 줄 삭제 + commit msg "deferred_heuristics 제거: <후보명>".

## 후보

- **`_external_only_check`** — `row_external_host.external_ratio≥0.95 AND total≥1` — github-wiki-see/tistory — `host_poly-pizza` (ratio=1.0/total=1, sponsor link) false-positive 위험 — 같은 패턴 미커버 호스트 1건 더 — commit `6c738e7`
- **`_multi_host_hub_check`** — `external_ratio≥0.95 AND ≥3 unique external hosts` — tistory — 단일 사례 over-engineering, `_external_only_check` 변형이라 그것 채택 시 흡수됨 — 플랫폼 hub root 2건째 (brunch/steemit/medium) — commit `6c738e7`
- **`cross_parent_aggregate_tile_pattern`** — 같은 class signature sibling 그룹이 same-class parent N개에 분산돼 누적 ≥10 — humblebundle/software (8×`div.mosaic-layout.threes`×3 tile=22) — `min_children=5` 게이트 우회 detector + LLM 활용 자리 (prompts/system) 동시 박아야 — mosaic/section-spanning aggregator 2건째 (showcase/store landing 류) — commit `host_humblebundle-co_software_4589b229` PR
- **`first_article_url_query_heavy_penalty`** — `pick_first_article_url` 가 `/search?sort=...&filter=...` 같은 query-heavy URL 을 깨끗한 `/path/machine-name` 보다 높게 픽 — humblebundle/software (`/store/search?sort=bestselling&filter=onsale` 먼저 픽) — 이번 케이스 list 0 본질 별개라 single-shot 효과 작음; 스코어링 가중치 재조정 후 회귀 확인 필요 — query-heavy first_article_url 오인 2건째 — commit `host_humblebundle-co_software_4589b229` PR
