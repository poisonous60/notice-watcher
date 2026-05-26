---
slug: host_wingamestore-co_news_902407e9
url: https://www.wingamestore.com/news/
status: ✅ registered by hand config after batch retry gen_fail
outcome: fixed
date: 2026-05-26
failure_keys: [gen_fail, validator_timeout, repeated_product_events]
fix_layer: config
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [games-batch, wingamestore, hand-config]
requested_by: round-2-retry-batch-20260526
---

## 조사 결과

Retry jobs `3185` and `3195` failed with gen_fail. The store news page is a product-event stream, not article news:
multiple rows can point at the same product URL with different event timestamps.

## 픽스

Added `configs/host_wingamestore-co_news_902407e9.json`. `post_id` combines product id and event timestamp text so
same-product release/sale events do not collide.

Local validation: 20 posts, first article body 18495 chars.
