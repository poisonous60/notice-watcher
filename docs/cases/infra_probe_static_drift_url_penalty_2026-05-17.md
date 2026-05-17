---
slug: infra_probe_static_drift_url_penalty_2026-05-17
url: (인프라 case — 특정 사이트 X. 트리거 = 사용자 비판 "5건째도 보류 6건째도 보류 — 언제 박는데" 의 트랙 B 부분)
status: 🏗 인프라 (probe 휴리스틱 lift — static_vs_headless rule 2 + first_article_url query penalty)
outcome: improved
date: 2026-05-17
fix_layer: C+A
failure_keys: [static_vs_headless_repeat_diff, first_article_url_query_heavy, prompt_static_insufficient_signal, deferred_heuristic_moving_target]
config_strategy:
adapters_changed:
engine_files_touched: [probe/extract.py, probe/diagnose.py, prompts/config_writer.system.txt, tests/probe_heuristics/test_static_vs_headless_check.py, tests/probe_heuristics/test_article_url_score.py]
tags: [self-improvement, probe-heuristic, deferred-heuristic-lift, static-headless-drift, first-article-url-penalty]
requested_by: 운영자 (dev box session)
---

## 트리거

직전 처리 (commit `7aa11c6`, host_humblebundle-co_software_4589b229) 에서 트랙 B 후보 2개 (`cross_parent_aggregate_tile_pattern` + `first_article_url_query_heavy_penalty`) 를 *또* deferred 로 미룸. 사용자: **"지난번 사이트 5개 줘서 보류였는데 6개일 때도 보류야. 대체 얼마나 더 해야 probe 개선하는건데"**.

`cases_index.py query --signal` 로 확인한 누적:
- static-vs-headless drift = 4건 (itch.io/jobplanet/piku/humblebundle)
- first_article_url 오인 = 6+건 (humblebundle/itch.io/jobplanet/nature/nexon/infra_reject)

본 case = 그 두 휴리스틱 박기. skill cross-case lookup 인프라는 별 case `infra_skill_cross_case_gate_2026-05-17.md`.

## 픽스 (fix_layer: C+A — 5 파일)

### C-1. `probe/extract.py:static_vs_headless_check` — rule 2 (selector-level diff) 추가

기존 rule 1 (size + row_signal): headless 가 정적의 2배 이상 + row-signal +5 → `static_insufficient=True`. piku 같은 진짜 빈 shell 검출.

새 rule 2 (selector-level diff): `html_repeating_patterns` 의 selector 별 child_count 비교. headless 에만 등장 (또는 정적의 3배 이상 + diff≥5) 인 selector 들의 합 ≥ **20** → `static_insufficient=True`, `trigger_rule="repeat"`.

humblebundle/itch.io/jobplanet 같은 *부분적* 빈 shell (정적엔 nav/header 다 있고 콘텐츠 mosaic 만 JS) 검출. 4 fixture 검증:
- humblebundle: ratio=1.25 (rule 1 미발화), repeat=51 → trigger=repeat ✓
- itch.io: ratio=1.01, repeat=46 → trigger=repeat ✓
- jobplanet: ratio=1.08, repeat=79 → trigger=repeat ✓
- piku: ratio=3.26 → trigger=size (회귀 OK, rule 1 그대로)

### C-2. `probe/diagnose.py` — rule 1 vs rule 2 분기

rule 1 (강한 신호): `static_ok=[]` 무효화 → `recommended_strategy` 가 Playwright 로. 기존 동작 유지.

rule 2 (약한 신호): `static_ok` 유지 + notes 만 추가 — "⚠ 정적 응답 vs Playwright DOM 비교: headless 에만 mosaic/tile 류 반복 패턴 N개 추가됨. ... strategy=playwright_html + list.wait_selector. 단, 정적 응답 안 JSON 직접 파싱 가능하면 httpx_html 도 검토." LLM 이 list_html 보고 최종 판단.

회귀 검증: 34 probe 디렉토리 중 rule 2 새로 잡는 사이트 = 8건 — 다 이미 등록됐거나 (handcrafted) rejected 라 무해 (static_ok 그대로).

### C-3. `probe/extract.py:_article_url_score` — query-heavy penalty + clean path bonus

```python
# 페널티: query string 의 검색/필터/정렬 파라미터 — 글 페이지 아님
if re.search(r"(?:^|&)(sort|filter|search|keyword|query|q|page|category)=", q): s -= 3
# 페널티: path 가 검색·목록 엔드포인트
if re.search(r"/(search|list|index|all|category|tag|sort|filter)(?:/|$|\?)", path_l): s -= 2
# 보너스: path-only 깨끗한 URL (machine-name 패턴, query 없음)
if not sp.query and re.search(r"/[a-z0-9][a-z0-9_\-]{4,}/?$", path_l): s += 1
```

humblebundle 검증: `/store/search?sort=bestselling&filter=onsale` 점수 0, `/software/realm-giants-software` 점수 6. 회귀: 기존 fixture `/board/view/12345` 점수 8 유지.

### A-1. `prompts/config_writer.system.txt` — playwright_html 트리거 줄 *추가*

기존 줄 *유지* + 새 줄 *추가* (skill §6.1.A — system 룰 추가만, 수정/제거 X):

```
- "playwright_html" : JS 렌더 필요(Cloudflare 등 / SPA). httpx_html 과 같은 필드 + wait_selector. (verdict 가 "JS 실행 필요" 류, 또는 escalation_hint 가 시키면.)
- ⚠ playwright_html 추가 트리거 (2026-05-17): notes 에 "정적 응답에 반복 패턴 anchor 가 없음" / "정적 응답이 빈 shell" 경고 — JSON island 에서 tile/card 를 JS 가 그리는 사이트 (humblebundle/itch.io 류) → list.wait_selector 필수.
```

### deferred_heuristics 정리

본 case 박은 2개 (`cross_parent_aggregate_tile_pattern` → static drift rule 2 로 흡수, `first_article_url_query_heavy_penalty` → `_article_url_score` penalty 로 흡수) 를 `_deferred_heuristics.md` 에서 [lifted] 표시.

## 자가 점검 (§6)

1. **자리**: C (probe heuristic 2개 + diagnose 분기) + A (system prompt 새 줄 1개 추가).
2. **이전 케이스 (cross-case lookup)**: `cases_index.py query --signal "static.{0,5}headless|dynamic.id|spa.{0,5}cloudflare|JSON.island"` = 4건 누적, `--signal "diverging_first_article|wrong_first_article"` = 5건 누적. 둘 다 `track_b_trigger=true`.
3. **누구 깰까**: 0 사이트 등록 자체 깨지지 않음. 영향 17개 사이트 static_insufficient=True 잡힘 — rule 1 (강) 9건 기존부터, rule 2 (약) 8건 새로 — 다 static_ok 유지라 무해.
4. **검증**:
   - probe_smoke: 269 → 271 fixture, 0 FAIL
   - 4 영향 사이트 (humblebundle/itch.io/jobplanet/piku) trigger_rule 직접 확인
   - 34 probe 디렉토리 회귀 — rule 2 신호 8건, rule 1 (회귀 영향) 0건
   - _article_url_score 6 새 fixture + 4 기존 fixture 회귀 PASS
5. **outcome=improved, fix_layer=C+A, commit prefix `[fix-layer: C+A]`**.
6. **fixture**: static_vs_headless_check (humblebundle-like rule 2, 임계 19/25, no_base_url skip) + _article_url_score (search penalty, machine-name bonus, 회귀 view_id). probe_smoke stage 5 28/28 coverage 유지.
7. **트랙 B 0건 사유**: 본 case 가 *직접 트랙 B 후보 lift*. 추가 일반화 후보 없음 — 단 `_external_only_check`/`_multi_host_hub_check` 도 임계 넘었는데 본 PR scope 밖 (다음 round 또는 별 PR 사용자 결정).
