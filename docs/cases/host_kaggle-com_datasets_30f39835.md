---
slug: host_kaggle-com_datasets_30f39835
url: https://www.kaggle.com/datasets
status: ⚪ no_change — Kaggle datasets page renders reCAPTCHA challenge only in headless
outcome: no_change
date: 2026-05-21
failure_keys: [captcha, capability_blocked, no_board_rows]
fix_layer: none
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [academic, datasets, kaggle, recaptcha, no-change]
requested_by: batch
---

## 무엇이 일어났나

로컬에는 이 slug의 `.FAILED.json` 과 probe 산출물이 없어 live Playwright 렌더로 확인했다.

`https://www.kaggle.com/datasets` 는 headless Chromium에서 `Checking your browser - reCAPTCHA` 페이지로
고정됐다. 렌더 DOM 안에는 dataset 행이 없고 `a[href*="/datasets/"]` 매칭도 0건이었다.

## 판단

게시판성 자체는 Kaggle datasets 목록에 있지만, 현재 실행 환경에서 확인 가능한 렌더 결과는 목록이 아니라
reCAPTCHA challenge다. 우회성 세션/캡차 처리는 이번 allow-list 밖이고 정책상 자동 config 로 만들지 않았다.

## Track B 검토

- **2a 인식기 — X.** 단일 Kaggle datasets 목록이며, 차단을 해결하지 못한다.
- **2b article-url — X.** 첫 글 오인이 아니라 목록 렌더 접근 차단이다.
- **2c/2d probe/engine — X.** captcha 처리나 storage_state 운용은 allow-list 밖이다.
- **2e 수동 config — X.** row selector 를 검증할 실제 dataset rows 가 렌더되지 않았다.

일반화 안 되는 이유: 렌더 산출물이 사이트 컨텐츠가 아니라 reCAPTCHA challenge라 selector 작성 근거가 없다.

## 회귀 검증

- `preflight: miss — host_kaggle-com_datasets_30f39835` (로컬 config/probe/FAILED 산출물 없음)
- live render: title `Checking your browser - reCAPTCHA`, dataset row/link selector 0건.
- config 생성 안 함.
