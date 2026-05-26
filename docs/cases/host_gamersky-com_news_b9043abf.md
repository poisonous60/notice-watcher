---
slug: host_gamersky-com_news_b9043abf
url: https://www.gamersky.com/news/
status: ✅ registered by hand config after batch retry gen_fail
outcome: fixed
date: 2026-05-26
failure_keys: [gen_fail, validator_timeout, selector_drift]
fix_layer: config
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [games-batch, gamersky, hand-config]
requested_by: round-2-retry-batch-20260526
---

## 조사 결과

Retry jobs `3182` and `3193` failed with gen_fail. After the validator hard-timeout deploy the tail changed to
`validate_internal_timeout_25s`, so this was no longer the old no-JSON hang.

Probe candidates exposed the stable news list as `ul.pictxt.contentpaging > li`, but the page also has hundreds of
other `/news/` anchors and sidebar links. The hand config pins the list row instead of using broad anchors.

## 픽스

Added `configs/host_gamersky-com_news_b9043abf.json` with `a.tt` fields and `div.Mid2L_con` article content.

Local validation: 30 posts, first article body 1424 chars.
