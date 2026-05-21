---
slug: host_mdpi-com_journal_df52afcc
url: https://www.mdpi.com/journal/rss
status: ❌ capability_blocked (N100 production host cloudflare 403)
outcome: no_change
date: 2026-05-21
failure_keys: [capability_blocked, rss_fallback]
fix_layer: none
config_strategy: none
adapters_changed: []
engine_files_touched: []
tags: [academic-batch, mdpi, rss, config]
requested_by: batch-2026-05-21-academic-track-a
---

## 결과

원 URL `/journal/rss`는 이 네트워크에서 Access Denied를 반환했다. 대신 MDPI의 전역 RSS endpoint
`https://www.mdpi.com/rss`는 httpx로 200을 반환했고, `<item>` 100건에 title/link/description/pubDate가
있었다.

## 픽스 — 회수 (N100 에서 동작 X)

dev box(codex worktree)에서는 `/rss` httpx 200·item 100건이었으나, **실제 poller 인 N100 에서 register 시 `/rss` 403 Forbidden** (cloudflare 가 N100 IP 차단). dev box 와 production host 의 IP 평판 차이 — config 가 N100 에서 폴링 불가 → 추가했던 `configs/host_mdpi-com_journal_df52afcc.json` 회수. **capability_blocked 유지** (능력 한계, 정책 아님).

GoodbyeDPI 류는 ISP SNI 차단용이라 cloudflare IP 차단엔 무효. 향후: residential proxy 또는 mdpi 의 per-journal 인증 feed 만 가능.

## 검증 메모

- dev box httpx `/rss`: 200, RSS item 100건 (codex 관측)
- **N100 register `/rss`: 403 Forbidden** (`httpx_html._get_text` raise_for_status) → 회수 결정
- 원 URL `/journal/rss`: dev box 에서도 403
