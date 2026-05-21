---
slug: host_lens-org_lens_fbd1435c
url: https://www.lens.org/lens/
status: ⚪ no_change — Lens URL은 앱/검색 랜딩이며 반복 신규 항목 목록 아님
outcome: no_change
date: 2026-05-21
failure_keys: [not_a_board, search_landing, nav_links_only]
fix_layer: none
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [academic, lens, no-change, not-a-board]
requested_by: batch
---

## 무엇이 일어났나

로컬에는 이 slug의 `.FAILED.json` 과 probe 산출물이 없어 live Playwright 렌더로 확인했다.

`https://www.lens.org/lens/` 는 Lens 앱 소개/진입 랜딩이다. 렌더 DOM에는 Patent Search, Scholarly Search,
API/Data, PatSeq 등 제품/기능 진입 링크가 반복되지만, 날짜순 dataset/article/protocol 행 목록은 확인되지 않았다.

## 판단

board-ness 기준에서 거부했다. 이 URL은 검색 앱의 홈이고, 폴링 대상이 될 "새 항목 목록"이 아니다. Lens에서
추적하려면 구체적인 검색 결과 URL이나 컬렉션 URL이 따로 필요하다.

## Track B 검토

- **2a 인식기 — X.** 플랫폼 앱 홈을 보드로 확장하면 오탐 위험이 크다.
- **2b article-url — X.** 첫 글 후보가 아니라 검색 랜딩이다.
- **2c/2d probe/engine — 보류.** 검색 홈 거부 게이트는 allow-list 밖이다.
- **2e 수동 config — X.** 반복되는 것은 제품/메뉴 링크다.

일반화 안 되는 이유: 같은 페이지 안 링크가 검색 도구/기능 내비게이션이라 사용자 의도를 자동 결정할 수 없다.

## 회귀 검증

- `preflight: miss — host_lens-org_lens_fbd1435c` (로컬 config/probe/FAILED 산출물 없음)
- live render: `a[href]` 다수이나 Patent/Scholarly/API 앱 진입 링크 중심, dataset/article rows 없음.
- config 생성 안 함.
