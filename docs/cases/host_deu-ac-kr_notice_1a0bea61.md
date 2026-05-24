---
slug: host_deu-ac-kr_notice_1a0bea61
url: https://www.deu.ac.kr/notice
status: ✅ config registered from official DEU notice board
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

kruniv catalog URL `https://www.deu.ac.kr/notice`는 probe에서 404를 냈고 `verdict=분류 보류`로 capability_blocked 큐에 들어왔다. 루트 `https://www.deu.ac.kr/`는 정상 접근되며 대표 홈페이지 안의 공지사항 링크가 `/www/deu-notice.do`로 노출된다.

## 조치

`configs/host_deu-ac-kr_notice_1a0bea61.json`을 작성했다. 같은 공식 host의 대표 공지 게시판 `https://www.deu.ac.kr/www/deu-notice.do`를 `playwright_html`로 수집한다.

주요 selector:

- list row: `table tbody tr`
- title/url: `td.subject a[href*='articleNo=']`
- body: `div.fr-view`

## 검증

- `python scripts/triage.py show host_deu-ac-kr_notice_1a0bea61`: 원 URL 404, 후보 0건.
- `python scripts/register.py --config configs/host_deu-ac-kr_notice_1a0bea61.json`: PASS, baseline 10건.
- 첫 글 body는 `div.fr-view`에서 100자 이상 추출된다.

## 일반화 후보

- 패턴: KR university catalog가 `/notice`를 잘못 생성했지만 실제 대표 공지는 CMS별 경로(`/www/deu-notice.do`, `/kor/CMS/Board/...`, `/bbs/BBSMSTR...`, `/kor/life/notice.do`)에 있다.
- 영향: `deu`, `dgist`, `pusan`, `smu`는 같은 catalog notice path noise로 회복됐다. `dhc`는 www host가 not-found shell이고 department subdomain만 발견되어 보류했다.
- fix layer 후보: B/A. kruniv catalog seed 또는 board URL 선택 prompt가 루트 페이지의 실제 "공지사항" 링크를 우선하도록 보강하는 후속 chunk가 맞다.
- 후속 chunk 필요: yes. ALLOW-LIST 밖인 catalog/probe/prompt 영역이므로 이 chunk에서는 config만 작성했다.
