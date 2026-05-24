---
slug: host_dhc-ac-kr_notice_af9d1dee
url: https://www.dhc.ac.kr/notice
status: ⚪ no change — www host has not-found shell; department subdomain out of scope
outcome: no_change
date: 2026-05-24
fix_layer: none
failure_keys: [capability_blocked, entry_blocked, catalog_notice_path_noise, not_found_shell]
config_strategy:
adapters_changed: []
engine_files_touched: []
tags: [kruniv, batch-2026-05-21, cap-blocked-retry, deferred]
---

## 무엇이 일어났나

probe verdict는 `ENTRY_BLOCKED`였지만 직접 확인 결과 `https://www.dhc.ac.kr/article/NOTICE/list`와 `https://www.dhc.ac.kr/main.do`는 "The requested page could not be found" shell만 반환한다. 검색 결과로 `liberalstudies.dhc.ac.kr/article/NOTICE/list` 계열 학과 공지사항은 확인됐지만, 이는 요청 host `www.dhc.ac.kr`의 대표 게시판이 아니다.

## 시도와 차단 신호

- probe artifact pull: `python scripts/triage.py pull --no-auto-defer` 성공.
- `triage.py show`: `verdict=ENTRY_BLOCKED`, 후보 0건.
- 직접 GET: `https://www.dhc.ac.kr/article/NOTICE/list` body text `The requested page could not be found. - DAEGU HEALTH COLLEGE -`.
- out-of-scope 후보: `https://liberalstudies.dhc.ac.kr/article/NOTICE/list`는 정상 목록이지만 학과 subdomain이다.

## 결정

config를 만들지 않았다. department subdomain을 대신 등록하면 사용자가 요청한 대표 host와 다른 board를 감시하게 된다.

## 일반화 후보

- 패턴: KR university catalog `/notice`가 존재하지 않는 대표 host shell을 만들고, 검색에는 학과/부서 subdomain 공지가 섞인다.
- 영향: `dhc` 단독으로 강한 scope contamination 신호가 있다. `deu`는 대표 host에서 실제 공지를 찾았으므로 다르다.
- fix layer 후보: C/B. 후보 URL discovery가 same-host 대표 board와 department subdomain을 구분하는 신호를 더 노출해야 한다.
- 후속 chunk 필요: yes. ALLOW-LIST 밖 probe/catalog 개선 후보로 넘긴다.
