---
slug: host_emerald-com_insight_87b0fd86
url: https://www.emerald.com/insight/
status: no_change (capability_blocked)
outcome: no_change
date: 2026-05-21
failure_keys: [capability_blocked, cloudflare_challenge]
fix_layer:
config_strategy:
adapters_changed: []
engine_files_touched: []
tags: [academic-batch, cloudflare, anti-bot, no-config]
requested_by: batch-2026-05-21-academic-track-a
---

## 결과

정적 httpx와 Playwright+stealth 모두 Cloudflare challenge 화면을 받았다.

## 판단

실제 insight 목록 DOM까지 도달하지 못했으므로 `wait_selector`/`row_selector`를 확정할 수 없다.
config 없이 no_change로 기록한다.

## 검증 메모

- httpx: 403, `Just a moment...`
- Playwright+stealth: 403/challenge DOM
- outcome: `no_change`
