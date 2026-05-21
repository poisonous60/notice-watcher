---
slug: host_papers-ssrn-com_sol3_77a5e762
url: https://papers.ssrn.com/sol3/DisplayAbstractSearch.cfm
status: no_change (capability_blocked)
outcome: no_change
date: 2026-05-21
failure_keys: [capability_blocked, cloudflare_challenge]
fix_layer:
config_strategy:
adapters_changed: []
engine_files_touched: []
tags: [academic-batch, ssrn, cloudflare, anti-bot, no-config]
requested_by: batch-2026-05-21-academic-track-a
---

## 결과

정적 httpx와 Playwright+stealth 모두 Cloudflare challenge 화면을 받았다.

## 판단

SSRN 검색 결과 목록 DOM까지 도달하지 못했다. captcha/challenge 우회는 범위 밖이므로 config를 만들지 않았다.

## 검증 메모

- httpx: 403, `Just a moment...`
- Playwright+stealth: challenge DOM
- outcome: `no_change`
