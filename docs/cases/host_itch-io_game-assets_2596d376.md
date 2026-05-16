---
slug: host_itch-io_game-assets_2596d376
url: https://itch.io/game-assets/genre-platformer/tag-3d
status: 🔧 손 config (httpx_html) — probe 가 JS 추가 id `#game_grid_0` 픽 → 정적 fetch 매칭 0
outcome: handcrafted
date: 2026-05-16
requested_by: poi23619
failure_keys: [posts_nonempty_0, dynamic_id_selector, static_vs_headless_selector_drift]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [itch.io, game-assets, dynamic-id, static-headless-drift, asset-aggregator, body-empty-acceptable]
---

## 무엇이 일어났나
사용자(`poi23619`) `/preview https://itch.io/game-assets/genre-platformer/tag-3d` → 자동 등록 retry 3회 FAIL — `[FAIL] posts_nonempty: 0건`.

last_config 의 row_selector `#game_grid_0 > div.game_cell` 는 probe headless HTML(JS rendered) 에만 존재. 실제 httpx 정적 fetch 응답엔 `id="game_grid_0"` 없음 — wrapper 는 `<div class="game_grid_widget base_widget browse_game_grid">` 뿐 (id 는 JS 가 동적으로 부여). 결과: 정적 fetch 36개 game_cell 다 매칭 0.

## 픽스
손-config: `row_selector: div.browse_game_grid > div.game_cell` — class 기반. 정적/headless 양쪽 매칭 36건.
- post_id: `:self` `data-game_id`
- url: `a.title` href (itch.io 서브도메인으로 외부)
- title/author/summary/cover_image 정상

`article.body_empty_acceptable: true` — 에셋 카드 aggregator. 외부 itch 서브도메인이 본문 호스트.

스모크: `make_adapter` → list 10건 OK, body 0자 OK (flag).

## 트랙 B (일반화 후보)
- **2a (인식기) — X.** itch.io 단일 게시판 등록. 같은 사이트의 다른 game-assets 카테고리(genre-*/tag-*)는 같은 패턴이지만 인식기는 별 PR (URL slug template + builder).
- **2b (--article-url) — X.** first_article_url 잘못 잡힘 (`/c/5267873/save` = 컬렉션) 이지만 article-url 교정으론 list selector 본질 못 풀음.
- **2c (probe heuristic 신규) — O (별 PR).** "selector 가 정적 HTML 에 안 보이는 동적 id (`#xxx_N` 패턴) 만으로 시작" 검출 → list_candidates entry 에 `selector_static_safe: bool` 박기. 본 PR 에선 미구현 — 기존 `static_vs_headless_check` (size/row-signal 비교) 와 별개 차원 (selector specificity). 1건만으로 별 PR 가치 boundary — 사례 누적 후 박을 것.
- **2d (probe artifact 수정) — X.** list_candidates 추출 자체는 정상.
- **(E) schema — X.** schema 통과한 config 였음.

일반화 안 되는 이유: dynamic-id selector drift 검출은 휴리스틱 자체는 5줄이지만 활용 자리 (`prompts/config_writer.system.txt` + selector 후보 ranking) 동시 박아야 가치. 본 PR scope 밖.

## 자가 점검 (§6)
1. **자리**: none (손-config). 미래 동일 패턴 누적 시 (C).
2. **이전 케이스**: 없음. dynamic-id-only selector 가 정적엔 없는 first instance.
3. **누구 깰까**: 0 (handcrafted 단건).
4. **검증**: probe_smoke PASS 272/0/4/0. 손-실행 list=10 OK.
5. **outcome=handcrafted, fix_layer=none, commit prefix `[fix-layer: none]`** (이 case 만으로는 일반화 안 박음).
6. **fixture**: skip (새 strategy/휴리스틱 아님).
7. **트랙 B 0건 사유**: 위 §트랙 B.
