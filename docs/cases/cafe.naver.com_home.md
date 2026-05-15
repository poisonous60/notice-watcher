---
slug: naver-cafe_gutterlife_all_e0009e69
url: https://cafe.naver.com/gutterlife
status: ✅ 자동 (recognizer 확장 — cafe 홈 URL 인식, NaverCafeAdapter 가 cafe_slug→cafe_id 런타임 해소)
date: 2026-05-16
fix_layer: F
failure_keys: [posts_nonempty]
config_strategy: handwritten
adapters_changed: [NaverCafeAdapter]
engine_files_touched: [engine/recognizers/naver_cafe.py]
tags: [naver-cafe, recognizer-extend, cafe-home, slug-resolve]
---

## 무엇이 일어났나
`https://cafe.naver.com/gutterlife` — 네이버 카페 홈 URL (특정 게시판 아님). 기존 인식기는 `/f-e/cafes/<id>/menus/<id>` 같은 게시판 URL 만 매칭 → 홈 URL 폴백 → probe + Gemini 시도. 카페 홈은 SSR HTML 에 *최신 댓글* (`#first-reply-page > li`) 만 있고 글 행 없음 → `[FAIL] posts_nonempty: 0건` 4회 retry fail.

같은 패턴 ( `cafe.naver.com/<slug>` 홈 URL ) 이 미래에 또 큐에 쌓이는 걸 막으려면 손-config 하나 박는 것보다 인식기·어댑터 확장이 옳음.

## 무엇을 바꿨나

### 1. `adapters/navercafe.py` — `cafe_slug` 런타임 해소
- 기존 `__init__(cafe_id, menu_id, …)` → `cafe_id` 또는 `cafe_slug` 중 하나만 받게.
- `cafe_slug` 만 있으면 `__aenter__` 에서 카페 홈 HTML (`https://cafe.naver.com/<slug>`) 한 번 GET → `g_sClubId` 정규식 스크랩 → `cafe_id` 채움. 기존 호출자 호환.
- 비공개 카페는 홈 HTML 응답에 `g_sClubId` 없음 → `ValueError("...비공개 카페 가능성")`.

### 2. `engine/recognizers/naver_cafe.py` — 홈 URL 패턴 추가
- 새 패턴 `//(?:m\.)?cafe\.naver\.com/([A-Za-z0-9_-]+)/?(?:\?|#|$)` (다른 패턴 폴백 뒤).
- builder `_home(m, url)` → cfg(`adapter:NaverCafeAdapter`, `kwargs:{cafe_slug:..., menu_id:0, include_notices:False}`).
- `menu_id=0` = "전체글" (모든 게시판 합본) — 카페 boardlist API 가 받음.
- `include_notices=False` — 홈 menu 의 sticky 공지 API 가 빈 배열만 줌.
- `_slug_board: f"{cafe_slug}_all"` — cafe_id 가 recognize 시점에 없으므로 slug 기반.
- 예약 segment(`f-e`, `cafes`) 는 홈으로 오인 X (다른 패턴이 먼저 매칭하지만 폴백 시 가드).

### 3. 검증
- 4건 (`gutterlife`, `crkingdom`, `cardmvk`, `cyworldnateid`) 모두 `fetch_list` 15건 / `cafe_id` 해소 OK. crkingdom 은 본문 8KB, 나머지 3곳은 401/403 → 본문 0자(가입·등급 필요, 어댑터가 본문 비워 반환). 정상 동작.
- `python scripts/register.py "https://cafe.naver.com/gutterlife"` → 인식기 매칭 → baseline 30건 등록 (slug `naver-cafe_gutterlife_all_e0009e69`).
- 기존 패턴 (`/f-e/cafes/<id>/menus/<id>`, `/ArticleList.nhn`) 매칭 보존.
- `probe_smoke.py` PASS 194/FAIL 0.

## 슬러그 스키마 영향
이 URL 은 기존 fallback 으로 `host_cafe-naver-com_<slug>_<hash>` 였음. 이제 인식기 매칭 → `naver-cafe_<slug>_all_<hash>`. **기존 successful 등록 0건** (어차피 다 FAIL 이었음) → migrate 불필요. 다만 dev 박스의 orphan `.FAILED.json` + triage_queue 항목은 새 slug 와 무관하므로 수동 정리 (이 케이스에서 수행).
