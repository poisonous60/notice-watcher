---
slug: host_curseforge-com_skyrim_4a37de3b
url: https://www.curseforge.com/skyrim
status: "✅ handcrafted — curseforge recognizer (game hub + category)"
outcome: handcrafted
fix_layer: F
failure_keys: [heterogeneous_hub_check_reject, classifier_catalog_reject]
config_strategy: playwright_html
date: 2026-05-27
engine_files_touched: [engine/recognizers/curseforge.py]
trigger_catalog: 2026-05-24-games-mods-hub
tags: [recognizer, mod-hub, cloudflare, curseforge]
related_commits: ["4ee32d4"]
---

# CurseForge game hub + category recognizer

## root cause

`https://www.curseforge.com/<game>` hub URL — 1 게임 hub 가 여러 카테고리 nav (`/minecraft`, `/games`) dominant 라 `_heterogeneous_hub_check` post-mortem 거부:

> "이질 카드 hub (gen_fail post-mortem): clean article cluster 1종 (max cc=10, cc=10 /skyrim/mods/...) 인데 competing nav max cc=18 (top: cc=18 /minecraft; cc=8 /games) 가 dominant"

게이트가 "board-shape sub-URL 또는 RSS 권장" — recognizer 가 sub-URL 또는 정확 listing 으로 redirect.

## fix

`engine/recognizers/curseforge.py` 신설 — URL form 별 두 builder:

- **`/<game>/<category>`** (예: `/minecraft/mc-mods`, `/wow/addons`): search URL `/<game>/search?class=<category>&sortBy=newest&page={page}&pageSize=20` 로 폴링. row_selector: `div.results-container > div.project-card`. post_id: `a.download-cta` href 의 `/download/(\d+)`.
- **`/<game>` (hub)**: 정적 게임 hub 페이지의 "shelf" 섹션 폴링. row_selector: `section.shelf .desktop-only ul.tiles-list > li.project-tile`. post_id: `a.btn-cta[href*='/install/']` 의 `/install/(\d+)`.

agentic 이 3 done (minecraft hub/mc-mods/sims4 — id ≥4078 batch) 에서 찾은 selectors 기반. `disable_stealth: true` + timing trim (nav 12s/idle 3s/quiet 250ms).

## 검증

- N100 9 retry (id≥4414): 6 done / 2 cap_blocked (modpacks·subnautica) / 1 rc=3 (rimworld).
- 전체 curseforge 12 → 9 done (기존 3 + 신규 6) / 2 cap_blocked / 1 rc=3 = 75%.

## 일반화 후보

- 다른 game-mod-hub 사이트가 (a) game root + (b) category sub-URL 두 form 갖는 패턴 — `_build_game` / `_build_category` 두 builder 구조 재사용 가능.

## 남은 작업

- rimworld rc=3 + modpacks/subnautica cap_blocked — 별 진단 (CF 강도 차이 또는 page 구조 차이).
