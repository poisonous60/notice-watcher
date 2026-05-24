---
slug: host_smu-ac-kr_notice_0fd72603
url: https://www.smu.ac.kr/notice
status: ✅ config registered from official SMU notice board
outcome: handcrafted
date: 2026-05-24
fix_layer: none
failure_keys: [capability_blocked, catalog_notice_path_noise, wrong_board_url]
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [kruniv, batch-2026-05-21, cap-blocked-retry, catalog-noise]
---

## 무엇이 일어났나

`https://www.smu.ac.kr/notice`는 404였고 batch에서는 `BASELINE_BLOCKED`로 분류됐다. 대표 홈페이지는 `/kor/index.do`로 redirect되며 통합공지 링크가 `/kor/life/notice.do`로 노출된다.

## 조치

`configs/host_smu-ac-kr_notice_0fd72603.json`을 작성했다. 상명대학교 통합공지의 카드형 `dl.board-thumb-content-wrap` 목록에서 `articleNo`를 추출한다.

주요 selector:

- list row: `dl.board-thumb-content-wrap`
- title: `dt td:nth-of-type(3) a[href*='articleNo=']`
- body: `div.board-view-content-wrap, div.board-view-content, div.view-con, div.fr-view`

## 검증

- `python scripts/triage.py show host_smu-ac-kr_notice_0fd72603`: 원 URL 404, 후보 0건.
- `python scripts/register.py --config configs/host_smu-ac-kr_notice_0fd72603.json`: PASS, baseline 30건.
- 첫 글 body는 상세 페이지에서 100자 이상 추출된다.

## 일반화 후보

- 패턴: KR university catalog `/notice` path가 실제 대표 통합공지 URL을 놓친다.
- 영향: `deu`, `dgist`, `pusan`, `smu`가 같은 URL discovery 문제다.
- fix layer 후보: B/A. catalog seed와 prompt가 루트의 공지 링크 텍스트 및 search result canonical URL을 반영해야 한다.
- 후속 chunk 필요: yes. 이 작업의 ALLOW-LIST 밖이므로 case에 escalate 정보만 남긴다.
