---
slug: host_dgist-ac-kr_notice_574f5305
url: https://www.dgist.ac.kr/notice
status: ✅ config registered from official DGIST Notice board
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

`https://www.dgist.ac.kr/notice`는 404 계열 진입 실패였고 batch에서는 `BASELINE_BLOCKED`로 분류됐다. 루트 `https://www.dgist.ac.kr/kor/`에는 정보마당 > Notice > 일반공지 링크가 있고 실제 목록은 `/bbs/BBSMSTR_000000000066/list.do`다.

## 조치

`configs/host_dgist-ac-kr_notice_574f5305.json`을 작성했다. DGIST 일반공지 목록은 anchor가 아니라 `button onclick="fn_search_detail('<nttId>')"`로 상세 이동하므로 `onclick`에서 `nttId`를 추출하고 상세 URL template을 구성했다.

주요 selector:

- list row: `table tbody tr`
- post_id: `td.subject button[onclick*='fn_search_detail']`
- body: `div.ui.bbs--view`

## 검증

- `python scripts/triage.py show host_dgist-ac-kr_notice_574f5305`: 원 URL 404, 후보 0건.
- `python scripts/register.py --config configs/host_dgist-ac-kr_notice_574f5305.json`: PASS, baseline 20건.
- 상세 페이지는 본문 텍스트가 짧은 파일 공지 형태라 `div.ui.bbs--view` 전체를 body로 잡았다.

## 일반화 후보

- 패턴: KR university catalog가 `/notice`를 잘못 생성했고 실제 공지는 CMS board ID 기반 경로다.
- 영향: `deu`, `dgist`, `pusan`, `smu`가 같은 URL discovery 문제로 묶인다.
- fix layer 후보: B/A. 루트/대표 페이지에서 "공지사항/Notice/일반공지" 링크를 먼저 따라가도록 board URL discovery를 보강해야 한다.
- 후속 chunk 필요: yes. probe/prompt/catalog 변경은 ALLOW-LIST 밖이라 이 case에서는 escalate 정보만 남긴다.
