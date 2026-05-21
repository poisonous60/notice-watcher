---
slug: host_nowpublishers-c_Foundations-and-Trends_b2b19237
url: https://www.nowpublishers.com/Foundations-and-Trends
status: no_change (capability_blocked)
outcome: no_change
date: 2026-05-21
failure_keys: [capability_blocked, cloudflare_challenge, redirected_host]
fix_layer:
config_strategy:
adapters_changed: []
engine_files_touched: []
tags: [academic-batch, cloudflare, anti-bot, no-config]
requested_by: batch-2026-05-21-academic-track-a
---

## 결과

라이브 요청은 `www.emerald.com/Foundations-and-Trends`로 리다이렉트된 뒤 Cloudflare challenge를 반환했다.

## 판단

최종 host가 원래 slug와 다르고, Playwright+stealth도 challenge 이후의 목록 DOM에 도달하지 못했다.
config 없이 no_change로 기록한다.

## 검증 메모

- httpx: 403 Cloudflare challenge after redirect to `www.emerald.com`
- Playwright+stealth: challenge DOM
- outcome: `no_change`
