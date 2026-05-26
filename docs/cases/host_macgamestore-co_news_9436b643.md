---
slug: host_macgamestore-co_news_9436b643
url: https://www.macgamestore.com/news/
status: ✅ registered by hand config after batch retry gen_fail
outcome: fixed
date: 2026-05-26
failure_keys: [gen_fail, validator_timeout, repeated_product_events]
fix_layer: config
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [games-batch, macgamestore, hand-config]
requested_by: round-2-retry-batch-20260526
---

## 조사 결과

Retry jobs `3187` and `3196` failed with gen_fail. The page has the same product-event table shape as WinGameStore and
can repeat product URLs for distinct reviews/sales/releases.

## 픽스

Added `configs/host_macgamestore-co_news_9436b643.json`. `post_id` combines product id and event timestamp text, while
the article body uses the product page `main` content.

Local validation: 20 posts, first article body 6776 chars.
