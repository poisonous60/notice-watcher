---
slug: host_mdpi-com_journal_df52afcc
url: https://www.mdpi.com/journal/rss
status: solved (global RSS fallback)
outcome: handcrafted
date: 2026-05-21
failure_keys: [capability_blocked, rss_fallback]
fix_layer: E
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [academic-batch, mdpi, rss, config]
requested_by: batch-2026-05-21-academic-track-a
---

## 결과

원 URL `/journal/rss`는 이 네트워크에서 Access Denied를 반환했다. 대신 MDPI의 전역 RSS endpoint
`https://www.mdpi.com/rss`는 httpx로 200을 반환했고, `<item>` 100건에 title/link/description/pubDate가
있었다.

## 픽스

`configs/host_mdpi-com_journal_df52afcc.json`을 추가했다.

- strategy: `httpx_html`
- list URL: `https://www.mdpi.com/rss`
- row selector: `item`
- post_id: item link path
- published_at: `pubDate`의 `YYYY-MM-DD`
- article body: RSS summary 중심, article page 본문은 optional

## 검증 메모

- httpx `/journal/rss`: 403 Access Denied
- httpx `/rss`: 200, RSS item 100건
- `validate_config` + `make_adapter.fetch_list(page_size=100)`: 100건, duplicate post_id 0건
- 첫 article body는 0자이며 `body_empty_acceptable=true`로 의도적으로 완화
