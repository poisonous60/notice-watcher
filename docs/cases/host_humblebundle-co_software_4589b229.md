---
slug: host_humblebundle-co_software_4589b229
url: https://www.humblebundle.com/software
status: 🔧 손 config (playwright_html) — probe `pick_first_article_url` 가 `/store/search?...` 픽 + 정적 GET 응답엔 타일 anchor 없음 (JS 가 `<script id="landingPage-json-data">` JSON 에서 렌더)
outcome: handcrafted
date: 2026-05-17
requested_by: poi23619
failure_keys: [posts_nonempty_0, wrong_first_article_url, dom_only_in_headless, cross_section_tile_pattern]
fix_layer: none
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [humblebundle, software-bundle, bundle-aggregator, playwright, body-empty-acceptable, mosaic-layout, personal-use]
---

## 무엇이 일어났나
사용자(`poi23619`) `/preview https://www.humblebundle.com/software` (개인 알림 목적 — 새 소프트웨어 번들 등장 watch) → 자동 등록 4회 FAIL — `[FAIL] posts_nonempty: 0건` + `[warn] matches_probe_first_article: probe first_article_url='https://www.humblebundle.com/store/search?sort=bestselling&filter=onsale' 와 일치하는 글 URL 없음`.

원인 두 겹:
1. **probe `pick_first_article_url` 오인** — `/software` 페이지의 "Browse the Store" 헤더 링크 (`/store/search?sort=bestselling&filter=onsale`) 를 first_article_url 로 픽. 이게 preflight 의 article re-probe 도 그 URL 로 끌고 가서 `article.html` = store search 페이지 (canonical=`/store/search?...`, og:url=`/store`, title=`Games: On Sale`).
2. **목록 anchor 정적 GET 에 없음** — `httpx.get('/software')` 응답은 200/568K 지만 `<a href="/software/<name>">` anchor 는 0건. 번들 데이터는 `<script id="landingPage-json-data" type="application/json">` 안 JSON. 타일 `<a class="full-tile-view bundle">` 는 클라이언트 JS 가 그 JSON 에서 렌더. probe 의 `list.html` 은 Playwright 가 캡처한 *렌더 DOM* (sec-ch-ua headers 가 chromium/147 증거) 이라 22 타일 있었던 것.
3. **html_repeating_patterns 미캐치** — 렌더 DOM 에 22 타일 있어도 `min_children=5` 게이트는 단일 parent 의 sibling 만 셈. Humble Bundle 은 8 × `div.mosaic-layout.threes` × 3 tile 구조라 parent 별 3개 → 게이트 통과 X. `list_candidates.html_repeating_patterns` 상위 = `head>link/meta/script` + nav dropdown items 만.

## 픽스
수동 config `playwright_html`:
- `wait_selector: "a.full-tile-view.bundle"` (JS hydration 대기)
- `row_selector: "a.full-tile-view.bundle"` — 22 → 스모크 10건 / register baseline 22건
- `post_id` = href regex `/software/([^/?#]+)` (stable machine-name)
- `title` = `aria-label` → `regex_extract "^(.+?)(?:,\s*\d+\s*(?:Day|Hour|Minute|Second)s?\s*Left)?$"` (카운트다운 suffix 제거)
- `url` = href → `strip_query_fragment` (hmb_source tracking 제거) + urljoin
- `article.body_empty_acceptable: true` + `content: []` — 새 번들 등장 알림만 (개인용, 본문 X)

스모크 list=10, register baseline=22, `.FAILED.json`/`triage_queue.jsonl` 자동 정리.

## 트랙 B (일반화 후보)
- **2a (인식기) — X.** Humble Bundle 전 카테고리 (`/software`, `/games`, `/books`) 같은 패턴 가능하지만 사용자 요청 1건만으로 platform recognizer 박는 건 over-eng. 2건째 요청 (다른 카테고리) 들어오면 `engine/recognizers/humblebundle.py` 신설 — `PATTERNS = [(r"humblebundle\.com/(software|games|books)$", builder)]`, builder 가 본 config 와 동형 dict 반환.
- **2b (--article-url) — X.** first_article_url 오인이지만 list selector 본질 (정적 GET 에 anchor 없음) 못 풀음 — article-url 교정해도 row_selector 가 정적 매칭 0.
- **2c (probe heuristic 신규) — O (deferred).** `cross_parent_aggregate_tile_pattern` — 같은 class signature 의 sibling 그룹이 *여러 same-class parent* 에 분산돼 누적 N≥10 이면 후보로 올림 (min_children=5 게이트 우회). 이번 케이스 8×3=22 가 정확히 그 패턴. *`_deferred_heuristics.md` append* — 2건째 들어오면 박음.
- **2d (probe artifact 수정 — `pick_first_article_url` 스코어링) — O (deferred).** `/store/search?sort=...&filter=...` 같은 query-heavy URL 이 `/software/machine-name` 같은 깨끗한 path URL 보다 높게 점수받음 → query string ratio 페널티 + path-segment 안정성 보너스. 단, 이번 케이스에선 list 자체가 0 이라 first_article_url 교정해도 등록 안 됐을 것이라 *부수적*. 별 PR 가치 1건 더 누적 시.
- **(E) schema — X.** 자동 생성된 config 가 schema 통과 (`li.entity-block-container.js-entity-container` 셀렉터). 정적 매칭 0 은 schema 범위 밖.

일반화 안 박는 이유 한 줄: cross-parent tile aggregate / first_article_url query-heavy 페널티 둘 다 5줄 휴리스틱이지만 활용 자리 (prompts + ranking + 검증) 동시 박기 필요 → 2건째 들어와 가치 명확해질 때.

## 자가 점검 (§6)
1. **자리**: none (수동 config). 미래 2건째 → (C) cross-parent aggregate + `pick_first_article_url` query 페널티.
2. **이전 케이스**: 없음. `mosaic-layout × N section × M tile` 분산 구조의 첫 케이스. (`host_itch-io_game-assets_2596d376` 와 비슷한 "body_empty_acceptable=true 의 aggregator" 패턴이지만 그쪽은 단일 grid.)
3. **누구 깰까**: 0 (handcrafted 단건).
4. **검증**: 스키마 PASS, 스모크 list=10 OK, register baseline=22 OK. probe_smoke 는 §5 step 1 에서 pre-push hook 으로.
5. **outcome=handcrafted, fix_layer=none, commit prefix `[fix-layer: none]`**.
6. **fixture**: skip (새 strategy/휴리스틱 아님).
7. **트랙 B 0건 사유**: 위 §트랙 B — 2c/2d 후보 있지만 1건 누적으론 over-eng. `_deferred_heuristics.md` 에 append.
