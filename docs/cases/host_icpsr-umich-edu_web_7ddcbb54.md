---
slug: host_icpsr-umich-edu_web_7ddcbb54
url: https://www.icpsr.umich.edu/web/pages/
status: ⚪ no_change — 입력 URL은 ICPSR home/marketing page 로 redirect
outcome: no_change
date: 2026-05-21
failure_keys: [not_a_board, root_landing_page, redirected_home]
fix_layer: none
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [academic, icpsr, no-change, not-a-board]
requested_by: batch
---

## 무엇이 일어났나

로컬에는 이 slug의 `.FAILED.json` 과 probe 산출물이 없어 live Playwright 렌더로 확인했다.

`https://www.icpsr.umich.edu/web/pages/` 는 `https://www.icpsr.umich.edu/sites/icpsr/home` 성격의 홈으로
렌더됐다. 내비게이션과 서비스 소개, Find Data/Share Data/Help 링크가 중심이고 날짜순 study/dataset rows 는
이 URL에서 확인되지 않았다.

## 판단

board-ness 기준에서 거부했다. ICPSR 데이터 목록을 추적하려면 `/web/icpsr/search/studies?...` 같은 구체적인
검색 결과 URL이 필요하다. 입력된 `/web/pages/` 는 폴링 대상 목록이 아니다.

## Track B 검토

- **2a 인식기 — X.** 홈 URL을 데이터 목록으로 임의 치환하면 사용자 의도 오탐이 크다.
- **2b article-url — X.** 첫 글 오인이 아니라 redirect/home 문제다.
- **2c/2d probe/generate — 보류.** root landing gate 개선은 allow-list 밖이다.
- **2e 수동 config — X.** 이 URL 자체에 study rows 가 없다.

일반화 안 되는 이유: 데이터 검색 URL의 쿼리/필터를 사용자 의도 없이 자동 선택할 수 없다.

## 회귀 검증

- `preflight: miss — host_icpsr-umich-edu_web_7ddcbb54` (로컬 config/probe/FAILED 산출물 없음)
- live render: title `Data excellence. Research impact. | ICPSR`, navigation/marketing links 중심.
- config 생성 안 함.
