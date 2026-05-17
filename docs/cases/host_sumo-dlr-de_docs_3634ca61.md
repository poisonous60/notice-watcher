---
slug: host_sumo-dlr-de_docs_3634ca61
url: https://sumo.dlr.de/docs/Definition_of_Vehicles,_Vehicle_Types,_and_Routes.html
status: ❌ 거부 (mkdocs-style 정적 docs site — 게시판 아님)
outcome: rejected
date: 2026-05-17
fix_layer: F
failure_keys: [not_a_board, static_docs_site, same_page_anchor_first_article, post_id_unique]
config_strategy:
adapters_changed:
engine_files_touched: [engine/recognizers/article_page_reject.py, tests/recognizers/test_article_page_reject.py, docs/cases/_deferred_heuristics.md]
tags: [reject-marker, recognizer-fast-path, docs-site, mkdocs, sumo-dlr]
requested_by: poi23619 (bot /preview)
---

## 트리거

`/preview https://sumo.dlr.de/docs/Definition_of_Vehicles,_Vehicle_Types,_and_Routes.html` → 4-retry FAIL → `.FAILED.json`.

`last_feedback`: `[FAIL] post_id_unique: 중복 1건` (`a[href]` 가 nav + main 양쪽에서 같은 link 잡음). 직전 3 시도 다 같은 패턴.

`diagnosis.json`:
- verdict: `정적 HTTP로 충분` (강력한 차단 X)
- `article_entry_ok=True` (글페이지 본문 14512자)
- note: `정적 응답 vs Playwright DOM 비교: headless 에만 mosaic/tile 류 반복 패턴 131개 추가됨 (정적 393). 정적 HTML 의 <script id=*-json-data> 같은 JSON island 에서 클라이언트 JS 가 tile 렌더 가능성`

`list_candidates.json`:
- **`first_article_url=https://sumo.dlr.de/docs/index.html#data_sources_for_demand_generation`** ← `#anchor` (same-page section)
- repeating top: `div.col-md-9.main-area > p` cc=110 / `tbody > tr` cc=62 / `ul.nav.flex-column.bs-sidenav > li.nav-item` cc=54 — docs sidenav + main-area `<p>` 안의 anchor links
- `row_external_host`: total=6, external=0 (single-host)
- `nav_only_same_host=False` (outside_nav=6 — main-area 의 `<p>` 안 anchor links 가 nav 밖)
- `article_meta_signals=None` (정적 docs, og/schema 없음)

## 진단

§2g (not_a_board) — *static documentation site*. SUMO 는 DLR 의 Eclipse SUMO traffic simulator 의 mkdocs-material 기반 docs. 사용자가 특정 docs 페이지를 줬지만:
- "새 글" 개념 X — docs revision 이지 신규 post 아님 (notice-watcher 는 list 모니터)
- "list" 가 페이지 자체의 internal anchor + sidenav (정적 finite 목록)

기존 게이트가 못 잡은 이유:
- `recognize_reject`: 호스트 미커버
- `_single_article_nav_only_check`: outside_nav=6 (main-area `<p>` 안 anchor links 가 nav 밖)
- `_meta_article_diverging_check`: og/schema article 마크업 없음

매칭 `§2g (not_a_board, static-docs)`.

누적 cross-check (`cases_index.py query`):
- `post_id_unique` count=1 → trigger=false (단일)
- `post_id_stable_shape` count=5 → trigger (다른 영역 — article_page_reject 가 이미 cover)
- `static_vs_headless` count=5 → trigger (infra hint 이미 박힘)
- → docs-site 자체는 누적 1건 → deferred 후보로만 등록

## 픽스 (fix_layer: F — track A+B)

### F-1. `engine/recognizers/article_page_reject.py:PATTERNS_REJECT` — sumo.dlr.de/docs/ 추가

```python
(re.compile(
    r"^https?://sumo\.dlr\.de/docs/", re.I,
), "sumo.dlr.de/docs 단일 문서 페이지 — 게시판 아님. mkdocs-style 정적 문서, 새 글 발행 X (폴링 의미 없음)."),
```

`skip_learn=False` (default) — host_path_prefix=`/docs` 학습 OK. SUMO 의 다른 path (`/`, `/wiki/`, release notes 등) 가능성 → path_prefix 만 차단해 안전. host 의 root `https://sumo.dlr.de/` 는 통과 (테스트 `sumo_root_passes`).

### F-2. `tests/recognizers/test_article_page_reject.py` — case 41-43 추가

- 41: sumo docs single page (이번 URL) — 거부 + skip_learn=False
- 42: sumo docs index.html — 거부 (`/docs/` prefix 매칭)
- 43: sumo root (`/`) — 통과 (false positive 차단)

### F-3. `docs/cases/_deferred_heuristics.md` — `is_static_docs_site_first_article_anchor` 후보 append

같은 패턴 1건째 — 호스트 명시 패턴 이 적합 (휴리스틱 false positive 위험 > 가치). 2건째 들어오면 multi-signal AND 설계 재검토.

## 영향

- **sumo (이 case)** — `.FAILED.json` 정리 + `.REJECTED.json` 마커 박힘 + learned_blacklist `sumo.dlr.de + /docs` 학습 (다음 어떤 사용자가 같은 URL 또는 같은 path-prefix URL 줘도 url_gate 단에서 차단).
- **미래 sumo docs 사용자** — `/preview <any-sumo-docs-page>` 즉시 거부 메시지 "mkdocs-style 정적 문서, 새 글 발행 X".
- **다른 mkdocs/sphinx docs 사이트** — 미커버. 1건째라 호스트별 패턴만. 같은 패턴 누적 시 deferred heuristic 박을 것.

## 회귀 검증

- `python tests/recognizers/test_article_page_reject.py` → **43 PASS** (38 → +3, sumo case 3개).
- `python scripts/register.py "<sumo url>"`: ✅ recognize_reject 매칭, REJECTED 마커 박힘, learned_blacklist 자동 학습, triage_queue 정리.

## 트랙 B 매칭 (자가 점검 §6.7)

- **2a (인식기 PATTERNS_REJECT 확장)**: ✅ sumo.dlr.de/docs 패턴 추가.
- **2b (--article-url)**: ❌ 목록 자체 부재 — first_article_url 이 same-page anchor.
- **2c (probe heuristic `_static_docs_site_check`)**: ❌ 보류 (`_deferred_heuristics.md` append). 신호 (`first_article_url` fragment + path 동일 + sidenav cc≥20) 가 docs site 만 명확히 잡으나 — 1건째 (sumo). 같은 패턴 2건째 (`docs.rs/`, `vitepress` site 등) 들어오면 휴리스틱화 재검토.
- **2d (probe artifact 수정)**: ❌.

## 회수 (사용자가 다시 정확한 board URL 로 주는 경우)

SUMO 자체에 GitHub Releases (`https://github.com/eclipse-sumo/sumo/releases`) 또는 메일링 리스트가 있음. 사용자가 그 URL 로 다시 `/preview` 시 일반 파이프라인 (또는 GitHub releases 인식기 — 향후 추가 가능) 으로 등록.
