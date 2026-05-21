---
slug: host_jstage-jst-go-j_browse_b0d95528
url: https://www.jstage.jst.go.jp/browse/-char/en
status: 🔧 손 config 등록 후보 — J-STAGE latest issue rows playwright_html 10건 검증
outcome: handcrafted
date: 2026-05-21
failure_keys: [spa_render_required, issue_rows]
fix_layer: none
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [academic, jstage, journals, playwright-html]
requested_by: batch
---

## 무엇이 일어났나

로컬에는 이 slug의 `.FAILED.json` 과 probe 산출물이 없어 live Playwright 렌더로 확인했다.

J-STAGE browse home 은 일반 탐색 랜딩이지만, 렌더 DOM에 날짜순 최신 issue 목록이 있다.
`a.customTooltip[href*="/_contents/-char/en"]` rows 는 journal title, date, volume, issue 를 포함한다.

## 픽스

`configs/host_jstage-jst-go-j_browse_b0d95528.json` 생성. post_id 는
`/browse/<journal>/<volume>/<issue>/_contents/-char/en` 의 path 조각을 사용하고, 제목은 `title` 속성,
날짜/summary 는 row 안의 grey metadata 에서 추출한다.

## Track B 검토

- **2a 인식기 — X.** J-STAGE 플랫폼 recognizer 는 가능하지만 이번 allow-list 밖이다.
- **2b article-url — X.** 첫 글 오인이 아니라 browse page 안 latest issue section 선택 문제다.
- **2c/2d probe/generate — 보류.** latest issue section 자동 선별은 prompt/probe 개선이 필요하다.
- **2e 수동 config — O.** 렌더 DOM에서 최신 issue rows 가 안정적으로 확인된다.

일반화 안 되는 이유: browse page 안에는 journal 신규등록 섹션과 issue 섹션이 함께 있어 자동으로 어느 목록을 택할지 정하기 어렵다.

## 회귀 검증

- `preflight: miss — host_jstage-jst-go-j_browse_b0d95528` (로컬 config/probe/FAILED 산출물 없음)
- `validate_config` → OK.
- live adapter smoke → list 10건, first post `ivr/40/3`, article body 81815자.
