---
slug: _generic_catalog_gate_removed_shape_only
url: (generic)
status: "improved — catalog 자동거부 폐기, 게이트=shape only (ADR 0011 rev)"
outcome: improved
fix_layer: A+F
failure_keys: [classifier_catalog_false_reject, agentic_self_veto_non_board_catalog, static_catalog_row_selector_miss]
date: 2026-05-27
trigger_slugs: [host_nexusmods-com_skyrimspecialedition_5494dcb1, host_curseforge-com_skyrim_4a37de3b, host_gamebanana-com_games_80fcc639]
related_commits: ["fb8b605", "63ad27a", "61053d9", "afd113d"]
---

# Catalog 자동거부 폐기 — 게이트 = shape only

## root cause

ADR 0011 (2026-05-21) 가 catalog 페이지 (패키지 레지스트리·제품 카탈로그·mod hub) 를 *자동거부* 로 박았다. 가정: catalog 자동 등록 = 폴링 junk. 하지만 2026-05-24-games-mods-hub batch 에서 100/100 중 78건이 rc=3 catalog gate_reject 됨. 사용자가 직접 enqueue 한 entry 자체가 알람 의사 표명인데 시스템이 "원하지 않을 것" 으로 추측.

추가 관찰: catalog vs index 경계 자체가 ambiguous — mod hub (nexusmods/curseforge/modrinth/gamebanana/thunderstore) 는 각 카드가 *상세 페이지* (설명·changelog·코멘트 = 읽을 본문) 로 연결되어 사용자 보기 index, 분류기 보기 catalog 로 갈리며 false-reject.

## fix

세 layer 동시 박음 (mod hub batch 5 platforms 78/100 false-reject 봉합):

- **A-layer (게이트)** — `scripts/register.py:_CLASS_REJECT_RC` 에서 `catalog` 제거. content/not_found/login 만 거부 채널 유지. 게이트는 *shape* (config 만들 수 있나 = 반복 row 추출 가능) 판정, semantic (catalog vs index) 입력 X. `_accept_path_content_reject` 가 catalog conf≥0.7 더 이상 거부 X.

- **A-layer (agentic prompt)** — `prompts/config_writer.system.txt` + `prompts/register_agent_AGENTS.md` 의 self-veto 룰에서 catalog 항목 제거. agentic 도 catalog/registry/product listing 을 `non_board` self-veto 하지 않음. 단 반복 row 0~소수 + 단일 본문 인 경우는 그대로 `non_board`.

- **F-layer (Recipe 3)** — `generate/generator.py:_recipe_3_applies` 신설 (`static_catalog_row_retry`). `posts_nonempty` 반복 fail + NOT SPA + `html_repeating_patterns` 후보 ≥2 면 trigger. text hint: nested grid selector 시도 + published_at 생략 허용 가이드.

- **B-layer (few-shot)** — `generate/prompt.py:_EXAMPLE_CONFIG_FILES` 에 `nexusmods_skyrim_2c5be4f9.json` 추가 (mod hub catalog working config — playwright_html + nested grid + 일부 row 에 published_at, 일부 없음).

- **A-layer (prompt 가이드)** — `prompts/config_writer.system.txt` 에 catalog row 1줄 가이드 (nested grid row_selector, detail URL ID → post_id regex, published_at 생략 허용).

ADR 0011 갱신 (Revision 2026-05-27) — 폴링 junk 책임 이동 (시스템 자동 차단 → enqueue 시점, catalog yaml 작성자 / `/watch` 사용자 책임).

## 영향

2026-05-24-games-mods-hub batch retry — gate fix 만으로 비-nexusmods 32 중 9 done (gamebanana 5 + thunderstore 3 + curseforge 0 + modrinth 0; 단 thunderstore 가 일부 이전 done 포함). 이후 platform recognizer 3개 (nexusmods/curseforge/gamebanana) 박아 결정적 통과.

## 관련 case

- `host_nexusmods-com_skyrimspecialedition_5494dcb1` (recognizer 박힘 — handcrafted)
- `host_curseforge-com_skyrim_4a37de3b` (recognizer 박힘 — handcrafted)
- `host_gamebanana-com_games_80fcc639` (recognizer 박힘 — handcrafted)
