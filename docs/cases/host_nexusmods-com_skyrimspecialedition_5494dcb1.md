---
slug: host_nexusmods-com_skyrimspecialedition_5494dcb1
url: https://www.nexusmods.com/skyrimspecialedition
status: "✅ handcrafted — nexusmods recognizer (platform config)"
outcome: handcrafted
fix_layer: F
failure_keys: [classifier_catalog_reject, playwright_stealth_dns_race]
config_strategy: playwright_html
date: 2026-05-27
engine_files_touched: [engine/recognizers/nexusmods.py]
trigger_catalog: 2026-05-24-games-mods-hub
tags: [recognizer, mod-hub, cloudflare, nexusmods]
related_commits: ["fb8b605", "65744b7", "7b8df22"]
---

# Nexus Mods 게임 hub → mods 탭 (Recent Mods) recognizer

## root cause

`https://www.nexusmods.com/<game>` hub URL 등록 시도. 2회 차례 거부:

1. **1차 (catalog gate)**: 정적 HTML 보고 분류기가 `classifier=catalog conf=0.98` 판정 — `accept_path catalog 거부`. ADR 0011 의 catalog 자동거부 적용. (이 layer 는 [[_generic_catalog_gate_removed_shape_only]] 에서 봉합)

2. **2차 (DNS race + agentic fail)**: 게이트 풀고 reuse-probe → agentic config_writer → `api-router.nexusmods.com/graphql` 500 + Playwright `ERR_NAME_NOT_RESOLVED` (playwright_stealth DNS race).

53/59 catalog entry 가 같은 패턴 (nexusmods.com/<game>).

## fix

`engine/recognizers/nexusmods.py` 신설 — F-layer:

- 패턴: `nexusmods.com/<game>` 또는 `nexusmods.com/<game>/mods/` 매칭. 단일 mod URL (`/<game>/mods/<id>`) 또는 reserved sub (users/games/search 등) 은 fall through.
- builder: `/<game>` 받아 `/<game>/mods/?BH=4` (Recent Mods 정렬) 로 normalize.
- strategy: `playwright_html` + `disable_stealth: true` (`playwright_stealth.Stealth()` 의 DNS hook race 회피).
- row_selector: `div.mods-grid > div[data-e2eid="mod-tile"]` (nested grid).
- post_id: `a[data-e2eid="mod-tile-title"]` 의 href 에서 `/mods/(\d+)` 추출.
- published_at: `p[data-e2eid="mod-tile-uploaded"] time` 의 `datetime` 속성.
- timing: nav 12000ms / idle 3000ms / quiet 250ms (광고/tracking 으로 networkidle 안 옴, 축소 후 throughput ~50s → ~15s/건).

## 검증

- Dev box `register.py "https://www.nexusmods.com/skyrim"` → ✅ baseline 20 mods.
- N100 batch retry (id≥4291): nexusmods 58 entries → 49 done (rest = cap_blocked 5 + rc=3 1 + rc=4 3).

## 일반화 후보

각 게임 mod hub 사이트 (curseforge·modrinth·gamebanana 등) 도 동일 패턴 — *지정 카드 grid + each card → detail*. 별 recognizer 박음.
