---
slug: host_zenodo-org_communities_530e9968
url: https://zenodo.org/communities/
status: no_change (capability_blocked)
outcome: no_change
date: 2026-05-21
failure_keys: [capability_blocked, unusual_traffic_403]
fix_layer:
config_strategy:
adapters_changed: []
engine_files_touched: []
tags: [academic-batch, zenodo, anti-bot, no-config]
requested_by: batch-2026-05-21-academic-track-a
---

## 결과

정적 httpx는 `unusual traffic` 403을 반환했고, Playwright navigation도 같은 차단에 걸렸다.
`/api/communities`도 동일하게 403이었다.

## 판단

브라우저 렌더와 API 모두 차단되어 config로 수집할 row를 확인할 수 없다. 우회 처리는 범위 밖이므로
no_change로 기록한다.

## 검증 메모

- httpx `/communities/`: 403 unusual traffic
- httpx `/api/communities`: 403 unusual traffic
- Playwright+stealth: navigation interrupted by 403/chrome error page
- outcome: `no_change`
