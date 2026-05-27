---
slug: host_gamebanana-com_games_80fcc639
url: https://gamebanana.com/games/3
status: "✅ handcrafted — gamebanana recognizer (SubmissionsListModule scope)"
outcome: handcrafted
fix_layer: F
failure_keys: [agentic_grabbed_wrong_section_records_grid, playwright_stealth_dns_race, article_body_empty]
config_strategy: playwright_html
date: 2026-05-27
engine_files_touched: [engine/recognizers/gamebanana.py]
trigger_catalog: 2026-05-24-games-mods-hub
tags: [recognizer, mod-hub, cloudflare, gamebanana, deterministic-selector]
related_commits: ["bbe98d8"]
---

# GameBanana games hub → SubmissionsListModule(mods) scope 강제

## root cause

gamebanana games hub (`/games/<id>`) 에 여러 RecordsGrid 섹션 (mods / articles / threads / sounds / sub-games). 같은 catalog (2026-05-24-games-mods-hub) 의 10 entries 중 6 만 done, 4 fail (games/3, 4, 5, 5709) — agentic 이 *어느 grid 잡냐* 가 운:

- **games/3** probe 첫 글 = `https://gamebanana.com/articles/games/4254` ← articles 섹션 잡음, mods 아님. 시도한 row_selector `div#SubmissionsListModule .RecordsGrid > div.Record` matched 0.
- **games/4** probe 첫 글 = `/games/24426` ← sub-game tile (NavGames) 잡음.
- **games/5, 5709** = /mods/ 잡았지만 article body 추출 실패 (article CF timeout + `_sText` API path 짧음).

추가: `ERR_NAME_NOT_RESOLVED` (playwright_stealth DNS race) 1차 시도 깨먹음.

성공 6 (games/1,2,6,7,8,9) 의 agentic config 보면 5/6 가 `module#SubmissionsListModule div.RecordsGrid > div.Rendered.Record(.Flow.ModRecord.HasPreview)` 식의 scoped selector 사용 — 일관된 패턴. 실패 4 도 같은 hub 페이지지만 row_selector 가 mods 섹션 scope 강제 안 함.

## fix

`engine/recognizers/gamebanana.py` 신설 — F-layer:

- 패턴: `gamebanana.com/games/<id>` 매칭. 단일 mod / articles / sub-resource 는 fall through.
- url_template: `https://gamebanana.com/games/{board}` (hub URL — 그대로).
- **결정적 selector** (scope 박음):
  - `wait_selector` / `row_selector`: `module#SubmissionsListModule div.RecordsGrid > div.Record`
  - `row_required_selector`: `a.Name[href*='/mods/']` (mod 카드 한정 — articles row 자동 drop)
  - `post_id`: `a.Name[href*='/mods/']` 의 href 에서 `/mods/(\d+)` (fallback: `a.Preview`).
- strategy: `playwright_html` + `disable_stealth: true` (DNS race 회피).
- article: `/apiv12/Mod/{post_id}/ProfilePage` JSON API (`_sText` body), HTML CF challenge 우회.

## 검증

- Dev box `register.py "https://gamebanana.com/games/3"` → ✅ recognizer 매칭 fast-path, baseline 5건 (CS 1.6 mods).
- N100 4 retry (id≥4523): **games/3, 4, 5, 5709 모두 done**. fail 0.
- gamebanana 전체 10/10 등록.

## 일반화 후보

- "site root 가 다중 섹션 hub 인데 작업 대상은 한 섹션만" 패턴 — module ID 또는 component class 로 scope 강제하는 selector 디자인. agentic 이 자주 wrong-section 잡음 (NatGeo·CNN 류와 같은 류 — type-mix carousel).
- gamebanana article body 의 JSON API endpoint `/apiv12/Mod/<id>/ProfilePage` 가 일관된 API 형태 — 다른 gamebanana 서브리소스 (`/apiv12/<Type>/<id>/<View>`) 도 같은 형태일 가능성. future 사용 시 참고.

## 운 요소 제거

agentic + probe 가 *어느 RecordsGrid 잡냐* 라는 비결정성 — same URL, same code, 다른 결과. fix = recognizer 가 selector 강제. *모든 games/<id>* 가 같은 fast-path 로 결정적으로 처리.
