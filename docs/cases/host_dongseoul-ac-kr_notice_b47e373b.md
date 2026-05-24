---
slug: host_dongseoul-ac-kr_notice_b47e373b
url: https://www.dongseoul.ac.kr/notice
status: ⚪ no change — requested host connection refused/no reliable board URL
outcome: no_change
date: 2026-05-24
fix_layer: none
failure_keys: [capability_blocked, baseline_blocked, connection_refused, catalog_notice_path_noise]
config_strategy:
adapters_changed: []
engine_files_touched: []
tags: [kruniv, batch-2026-05-21, cap-blocked-retry, deferred]
---

## 무엇이 일어났나

probe verdict는 `BASELINE_BLOCKED`이며 로컬 직접 접근에서도 `https://www.dongseoul.ac.kr/`와 `/notice`가 연결 실패로 떨어진다. 검색으로도 같은 host의 대표 공지 board URL을 확인하지 못했다.

## 시도와 차단 신호

- probe artifact pull: `python scripts/triage.py pull --no-auto-defer` 성공.
- `triage.py show`: `BASELINE_BLOCKED`, `ConnectError: [Errno 111] Connection refused`.
- 직접 GET: `https://www.dongseoul.ac.kr/` 원격 서버 연결 실패.
- 검색: `site:www.dongseoul.ac.kr 공지사항`에서 신뢰 가능한 같은-host board URL을 찾지 못함.

## 결정

config를 만들지 않았다. 목록 URL과 selector를 검증할 수 없고, 다른 host/부서 페이지로 대체할 근거도 없다.

## 일반화 후보

- 패턴: catalog `/notice` noise가 connection-refused host와 결합되면 URL discovery가 더 진행되지 못한다.
- 영향: `dongseoul` 단독. `chonbuk`은 403/Cloudflare, `dhc`는 not-found shell이라 차단 표면이 다르다.
- fix layer 후보: C/B. host availability와 official board discovery의 실패 이유를 case body 수준이 아니라 probe digest에 더 구조화할 수 있다.
- 후속 chunk 필요: yes. ALLOW-LIST 밖 probe/catalog 개선 후보로 넘긴다.
