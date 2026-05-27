---
slug: host_annapurnaintera_root_105cae87
url: https://annapurnainteractive.com/
status: ❌ REJECTED — root URL = games catalog/marketing landing, no news board
outcome: rejected
date: 2026-05-28
fix_layer: none
failure_keys: [no_board, root_catalog_only, posts_nonempty]
config_strategy: none
adapters_changed: []
engine_files_touched: []
tags: [games-us-batch-2026-05-28, marketing-root, games-catalog, capability-blocked]
---

## 무엇이 일어났나

`2026-05-24-games-us` batch entry. `https://annapurnainteractive.com/` (Annapurna Interactive 게임 스튜디오 root). agentic max_cycles 4-retry × 2회 (`auto`→`agentic`) 모두 실패:

- 시도 1: `posts_nonempty: 0 rows` (root URL 직접 fetch — game tile/marketing)
- 시도 2: `fetch_list 404 /ko/games` (LLM 이 /ko/games subpath 추론 → 실제 URL 존재 X)

## 진단

§2 강제 인용:
- **0 live 확인**: `curl -sL https://annapurnainteractive.com/` → 200 OK 821KB marketing landing. `<title>Annapurna Interactive`. 본문 = game catalog hero + tiles (Outer Wilds, Stray, etc.). `/news/`·`/blog/` 경로 부재.
- 1 last_feedback: `posts_nonempty: 0 rows` / `fetch_list 404 /ko/games`
- 2 verdict: `정적 HTTP로 충분` (misleading — 통계만 보고 *news 아님* 못 봄)
- 3 매칭: §22 marketing-root / catalog-only
- 4a Track B 6-layer:
  - E miss — schema 거부할 만한 형태 아님 (config 빌드 자체가 무의미)
  - D miss — retry feedback 명확 (rows 0)
  - C miss — `root_marketing_homepage` 휴리스틱 가드: `board_shape` 가 51 game tiles 의 same-host rows 로 통과 → 게이트 미발화. 이를 더 좁히면 진짜 game forum/board root false-reject 위험
  - B miss — game catalog 전용 few-shot 작성 risk (다른 game 사이트 false-trigger)
  - A miss — classifier prompt 에 "games catalog tile rows ≠ news board" 박을 수 있으나 marginal benefit (단일 site, sister site magic.wizards 는 retry 시 `/en/news` 잡혀서 등록됨)
  - F miss — recognizer 추가할 패턴 없음 (annapurna 단일)
- 4b Track A: **skip** (사용자 ship evidence 0 — batch operator 흐름)
- 4c context: batch FAILED audit, ship 어휘 `Track A`/`수동 config`/`이 사이트 즉시 작동` 0건. user 명시 거부 의사 없음 + 사이트 진짜 news 부재 확인 → REJECT 동의.
- 4d park bucket: **REJECTED** (capability — site 가 news section 자체를 안 가짐. classifier fallthrough X — classifier 가 catalog 로 잘 판정해도 game tiles same-host rows 가 board_shape 통과시킴)
- 5 cases_index:
  - `failure_key=posts_nonempty` 131건 (광범위 — annapurna 특수성 없음)
  - `signal=marketing` 16건 (root_marketing_homepage 게이트 관련 — 이미 박힘)
- 6 preflight: miss (배치 entry, prior commit 영향 X)

## 무엇을 박았나

`_save_rejected(slug, url, reason, learn=False)` — N100 `.REJECTED.json` 마커. sibling cleanup (FAILED.json 삭제·triage_queue prune) 함수가 함.

`learn=False` — host annapurnainteractive.com 의 *다른 path* (예: 만약 미래에 `/blog` 또는 `/news` 추가되면) 등록 시도 보존. 현재 root URL 에만 적용.

## 왜 generic gate 아닌가

같은 패턴 (root URL = games catalog) 의 cross-site 사례 cases_index 누적 0 — 단일 site. 게이트 추가 시 false-positive (진짜 game 포럼/board 의 root) risk 가 benefit 보다 큼. 사용자 ship 요청 시 `/news` 또는 `/blog` subpath 로 재등록.

## 결과

- N100 `.REJECTED.json` 박힘 → 봇 응답 'rejected' (영구 거부)
- FAILED.json / triage_queue prune 자동
- 다음 batch 또는 사용자 `/preview` 시도 시 `is_blocked` 가 차단
