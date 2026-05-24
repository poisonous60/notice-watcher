---
slug: host_chonbuk-ac-kr_notice_d98e54a6
url: https://www.chonbuk.ac.kr/notice
status: ⚪ no change — Cloudflare/403 blocks requested host
outcome: no_change
date: 2026-05-24
fix_layer: none
failure_keys: [capability_blocked, cloudflare_protected_site, catalog_notice_path_noise]
config_strategy:
adapters_changed: []
engine_files_touched: []
tags: [kruniv, batch-2026-05-21, cap-blocked-retry, deferred]
---

## 무엇이 일어났나

`triage.py show` 기준 verdict는 `CLOUDFLARE_PROTECTED_SITE`다. 로컬에서도 `https://www.chonbuk.ac.kr/notice`와 대표 host 접근이 HTTP 403으로 막힌다. 검색 결과에서 `/web/Board/.../detailView.do` 형태의 전북대학교 게시글은 확인했지만, 같은 host의 목록 URL을 안정적으로 열어 selector를 검증하지 못했다.

## 시도와 차단 신호

- probe artifact pull: `python scripts/triage.py pull --no-auto-defer` 성공.
- `triage.py show`: `첫 4xx: 403 https://www.chonbuk.ac.kr/notice`.
- 직접 HEAD: `https://www.chonbuk.ac.kr/web/Board/92008/listView.do?menu=2377`도 403.

## 결정

config를 만들지 않았다. Cloudflare/403으로 목록과 상세를 smoke할 수 없고, 검색 결과의 detail URL만으로 board를 추정하면 scope 오염 위험이 있다.

## 일반화 후보

- 패턴: `/notice` catalog noise와 anti-bot 차단이 함께 나타난다.
- 영향: `chonbuk`은 Cloudflare 403, `dgist/pusan/smu/deu`는 URL discovery 보정으로 회복, `dhc`는 www shell, `dongseoul`은 connection refused.
- fix layer 후보: B/A for URL discovery, 별도 F/infra for stronger Cloudflare/session handling.
- 후속 chunk 필요: yes. ALLOW-LIST 밖인 probe/prompt/stealth/storage_state 쪽에서 다뤄야 한다.
