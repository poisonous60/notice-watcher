---
slug: host_dataverse-harva_dataverse_5133678a
url: https://dataverse.harvard.edu/dataverse/harvard
status: 🔧 손 config 등록 후보 — Harvard Dataverse datasetResult rows playwright_html 9건 검증
outcome: handcrafted
date: 2026-05-21
failure_keys: [spa_render_required, dataset_rows]
fix_layer: none
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [academic, dataverse, datasets, playwright-html]
requested_by: batch
---

## 무엇이 일어났나

로컬에는 이 slug의 `.FAILED.json` 과 probe 산출물이 없어 live Playwright 렌더로 확인했다.

`https://dataverse.harvard.edu/dataverse/harvard` 는 Harvard Dataverse 검색 결과 페이지이며, 렌더 후
`tr:has(div.datasetResult)` 에 날짜순 dataset rows 가 나타난다.

## 픽스

`configs/host_dataverse-harva_dataverse_5133678a.json` 생성. row에서 DOI persistentId 를 post_id 로 쓰고,
dataset title/url/date/summary 를 추출한다. 기사 본문은 dataset detail page 의 `#datasetForm, #content, body`
fallback 으로 둔다.

## Track B 검토

- **2a 인식기 — X.** Dataverse 플랫폼 일반화는 가능하지만 이번 hard-stop 은 configs/cases 로 제한됐다.
- **2b article-url — X.** 첫 글 오인이 아니라 JSF-rendered result rows 확인 문제다.
- **2c/2d probe/generate — 보류.** Dataverse recognizer/API 전환은 allow-list 밖이다.
- **2e 수동 config — O.** 렌더 DOM에서 dataset rows 가 안정적으로 확인된다.

일반화 안 되는 이유: Dataverse 인스턴스 일반화는 recognizer 또는 API 전략이 필요해 이번 범위를 넘는다.

## 회귀 검증

- `preflight: miss — host_dataverse-harva_dataverse_5133678a` (로컬 config/probe/FAILED 산출물 없음)
- `validate_config` → OK.
- live adapter smoke → list 9건, first post `doi:10.7910/DVN/A3QQ6Q`, article body 172753자.
