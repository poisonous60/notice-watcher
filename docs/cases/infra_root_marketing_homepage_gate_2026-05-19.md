---
slug: infra_root_marketing_homepage_gate_2026-05-19
url: (infra — 영구 게이트 박힘)
status: ✅ 영구 게이트 박힘 — root_marketing_homepage 휴리스틱 + register fail-fast + prompt 룰
outcome: improved
date: 2026-05-19
fix_layer: C
failure_keys: [root_marketing_homepage]
config_strategy: none
adapters_changed: []
engine_files_touched: [probe/extract.py, probe/_contract.py, scripts/register.py, scripts/probe.py, prompts/config_writer.system.txt, bot/fail_taxonomy.py, tests/probe_heuristics/test_root_marketing_homepage.py, tests/fail_taxonomy/test_classify_fail.py, docs/fail 분류.md]
tags: [infra, root-marketing-homepage, permanent-gate, fail-fast, llm-cost-zero]
requested_by: poi23619
---

## 무엇이 일어났나
FAILED 큐 4건 batch 처리 ([[host_edition-cnn-com_root_82356c05]] / [[host_nationalgeograp_root_2be4a852]] / [[host_reuters-com_root_9c8aa57a]] / [[host_vimeo-com_root_c6a102cf]]) — 모두 메이저 미디어/플랫폼 *root 도메인 URL* 의 자동 등록 시도. 본질적으로:
- root 페이지 = 마케팅 랜딩 + 카테고리 nav + hero carousel + (Reuters) SPA shell
- probe `diagnosis.verdict='정적 HTTP로 충분'` 이 *misleading* — root 페이지 구조 (nav-heavy, mixed paths) 미인식
- LLM 4-retry × 4 사이트 = 16번 호출 모두 실패

cases_index query 결과 누적:
- `post_id_unique=4건 track_b_trigger=true` (CNN + BBC + 기타)
- `post_id_stable_shape=7건 track_b_trigger=true`
- `posts_nonempty=17건 track_b_trigger=true`

→ 트랙 B 진입 강제 (CLAUDE.md §8a 영구 게이트 우선).

## 무엇을 박았나

### probe/extract.py:root_marketing_homepage (휴리스틱 자리 C)
새 `@heuristic` 함수. 트리거 조건 (AND):
1. URL path == `/` (또는 빈 path) — root 도메인
2. `html_repeating_patterns` top 7 중 selector 에 `nav/footer/header/dropdown/subnav/menu/carousel/swiper/tile/promo/hero/banner` 키워드 ≥ 2
3. `nav_only_same_host.total_same_host ≤ 15` (또는 None) — 진짜 article-grid root (HackerNews 류) false-positive 차단 가드

출력: `dict={is_root_marketing_homepage, marketing_hits, marketing_selectors, total_same_host, body_empty_likely}` 또는 `None`.

### probe/_contract.py:list_candidates.json 새 키
`root_marketing_homepage` (`dict|null`, required=False). prompt_aliases 없음. write 측 (`probe/extract.py:write_list_candidates`) 가 base_url 받아 호출.

### scripts/register.py:_root_marketing_homepage_check (게이트 자리 F)
`_board_shape_check` *전* 호출 — board_shape 의 `n_html_same >= 1` 만으로 통과되는 root marketing 페이지 (hero/carousel 의 same-host article 1-2개) 차단. LLM 호출 *전* fail-fast → 4-retry × 4 사이트 = 16번 비용 0.

`_save_rejected(..., learn=False)` — root 만 차단. 카테고리 path (`/world/`, `/business/`, `/photography/` 등) 는 진짜 board 가능성 있어 path_prefix 차단 X. 사용자에 안내: `카테고리/섹션 URL 시도 권장 — 예: <도메인>/<first_article_url 의 첫 segment>/`.

### prompts/config_writer.system.txt 1줄 (자리 A)
`list_candidates.root_marketing_homepage` 키 해석 룰 1줄 추가 — multi_host_hub 룰 옆. 게이트 우회 시에도 LLM 이 인지하고 "게시판 아님" 으로 멈춤.

### bot/fail_taxonomy.py + tests/fail_taxonomy/test_classify_fail.py
`gate_reject` FailKind 의 `subkinds` 에 `Subkind("root_marketing_homepage", ...)` 추가. CASES 에 `gate_root_marketing_homepage` fixture. doc regen → `docs/fail 분류.md`.

### tests/probe_heuristics/test_root_marketing_homepage.py
10 case fixture — 4 실제 사이트 (CNN/NatGeo/Reuters/Vimeo) 매칭 + 6 false-positive 가드 (HackerNews 류 grid / 카테고리 path / marketing 키워드 부족 / 빈 input).

## 효과 측정
- 4 사이트 모두 LLM 호출 0회로 REJECTED. 이전 4-retry × 4 = 16번 API 호출 차단.
- 미래 같은 패턴 (BBC root, NYTimes root, WaPo root, Vox root 류) 자동 처리. preview/watch 시도가 4-attempt LLM 사이클 대신 즉시 안내 메시지.
- `learn=False` 라 카테고리 URL (`/world/`, `/business/`) 은 *별도 board* 로 등록 시도 가능 — 기존 vocab_candidates (`row_type_filter_required`, `carousel_dedup_required`, `fingerprint_hide_required`, `tailwind_attr_selector_explosion`) 의 적용 자리 보존.

## 트랙 B 자리 매핑 (§6 1번)
- (C) probe digest 신호 — `root_marketing_homepage` 휴리스틱. 1순위.
- (F) 새 엔진 코드 — `_root_marketing_homepage_check` 게이트.
- (A) prompt 규칙 *추가* — `root_marketing_homepage` 키 해석 1줄.
- (B/D/E) 미해당.

위에서부터 차례 (E > D > C > B > A > F) 의 첫 매칭 = **C** (probe digest). F + A 는 같은 게이트 박는 *부속*.

## 자가 점검 (§6)
1. **자리**: C + F + A. 위 §트랙 B 매핑.
2. **이전 케이스**: `multi_host_hub_check` (tistory root 류) 가 *외부 host 발산* root 잡음. 본 게이트는 *same-host 내부 nav 우세* root 잡음 — 보완 관계. board_shape 의 false-pass 차단 자리도 비슷 (`_single_article_nav_only_check`, `_meta_article_diverging_check` 와 같은 류).
3. **누구 깰까**: 0 — 트리거 AND 조건 strict (root + 키워드 ≥ 2 + same-host rows ≤ 15). 21+ configs 영향 enumerate 결과 0.
4. **검증**: `probe_smoke` PASS 375 / FAIL 6 (모두 기존 stage 1/2 artifact freshness 회귀 — pre-push hook 의 stage 3+5 강제 통과). 4 사이트 `register.py --reuse-probe` → 모두 REJECTED.
5. **outcome=improved, fix_layer=C** (commit msg prefix `[fix-layer: C]`).
6. **fixture**: `tests/probe_heuristics/test_root_marketing_homepage.py` (10 cases) + `tests/fail_taxonomy/test_classify_fail.py` (`gate_root_marketing_homepage` 1 case).
7. **트랙 B 매칭**: 4건 동시 — C/F/A. 미래 카테고리 URL 권장의 *첫 segment 가 date (예: CNN `/2026/`) 인 경우* board 같은 워드 segment 우선 추출 후보 — `docs/cases/_deferred_heuristics.md` 에 append.
