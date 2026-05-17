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
- **`is_static_docs_site_first_article_anchor`** — `list_candidates.json` 의 `first_article_url` 의 fragment(`#anchor`) 떼고 보면 input URL 의 canonical 과 *같은 path 의 페이지* (자주 `index.html` 같은 hub) — same-page section anchor 또는 docs index. AND `nav_only_same_host=False` (`outside_nav>0`) 라 nav 게이트 통과. AND `article_meta_signals=None` (정적 docs 라 og:type 도 schema 도 없음). — sumo.dlr.de/docs (mkdocs material), 일반 정적 docs (Sphinx/Docusaurus/MkDocs) 가 잡힐 후보. **보류 사유**: 1건째 (sumo) 만 들어옴 — 호스트 명시 패턴(`article_page_reject.py`) 이 충분 + 휴리스틱 false positive 위험 (실제 보드인데 우연히 anchor link 가 첫 글로 잡힌 케이스 — 예: GitHub README hash-link 가 있는 보드). 재검토 트리거: docs site 같은 패턴 1건 더 들어오면 + multi-signal AND (anchor + sidenav cc≥20 + first_article path==input path) 안전하게 설계 가능할 때. — 최초 commit: 미정 (지금은 아이디어만)
- **`is_article_with_recommendation_widget`** — input URL 의 마지막 path segment 가 id-like (`\d{3,}` / `-\d+` / `[A-F0-9]{16,}` / `?id=<token>`) AND row 들이 input 의 *형제* (같은 path-prefix, 마지막 segment 만 다름) — `list_candidates.html_repeating_patterns` 의 sample_url 이 input path 의 parent + 다른 마지막 segment — iln-ieee/jobplanet 류 article 페이지 + 추천글 위젯 잡음 (nature 는 article_meta_signals 가 잡음). **보류 사유**: false positive 위험 큼 — `/board/123` 같은 *id-like board URL* (실제 board 인데 형식상 article 처럼 보임) 도 잡힐 가능성. URL pattern 단독 신호 위험성 사용자와 검토 (2026-05-17 dev box session). 재검토 트리거: iln/jobplanet 외 같은 패턴 1건 더 들어오면 + 안전한 multi-signal AND 설계 (예: row 들의 path 자식/형제 정밀 분류) 가능할 때. — 최초 commit: 미정 (지금은 아이디어만)
