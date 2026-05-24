---
slug: host_pusan-ac-kr_notice_88427aed
url: https://www.pusan.ac.kr/notice
status: ✅ config registered from official PNU notice board
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

`https://www.pusan.ac.kr/notice`는 probe에서 baseline blocked/404로 떨어졌지만, 검색 및 직접 검증 결과 대표 공지사항은 `https://www.pusan.ac.kr/kor/CMS/Board/Board.do?mCode=MN095`다.

## 조치

`configs/host_pusan-ac-kr_notice_88427aed.json`을 작성했다. 부산대학교 CMS Board의 `board_seq`를 post_id로 쓰고 상세 본문은 `div#boardContents`에서 추출한다.

주요 selector:

- list row: `table tbody tr`
- title/url: `td.subject a[href*='board_seq=']`
- body: `div#boardContents`

## 검증

- `python scripts/triage.py show host_pusan-ac-kr_notice_88427aed`: 원 URL 후보 0건, first_article_url 없음.
- `python scripts/register.py --config configs/host_pusan-ac-kr_notice_88427aed.json`: PASS, baseline 20건.
- 첫 글 body는 `div#boardContents`에서 100자 이상 추출된다.

## 일반화 후보

- 패턴: KR university catalog `/notice` path가 대표 CMS board를 놓친다.
- 영향: `deu`, `dgist`, `pusan`, `smu`가 동일 계열이다.
- fix layer 후보: B/A. catalog/probe가 루트 내 공지 링크와 검색 결과의 실제 board URL을 우선해야 한다.
- 후속 chunk 필요: yes. ALLOW-LIST 밖 변경 없이 per-site config로만 회복했다.
