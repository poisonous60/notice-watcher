---
slug: host_opencritic-com_news_ef0b3c95
url: https://opencritic.com/news/
status: ✅ registered by hand config after batch retry gen_fail
outcome: fixed
date: 2026-05-26
failure_keys: [gen_fail, validator_timeout, mixed_article_and_game_rows]
fix_layer: config
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [games-batch, opencritic, hand-config]
requested_by: round-2-retry-batch-20260526
---

## 조사 결과

Retry jobs `3172` and `3192` failed with agentic gen_fail after the infra timeout fix. The second retry no longer
reported `validator_hang/no_json`; it returned structured `validate_internal_timeout_25s`, which means the orchestration
bug was gone and the remaining failure was selector choice.

Probe HTML showed two competing row families on the same page: `app-short-game-list > a.deco-none` for game cards and
`div.mt-4 > div` for news rows. The generated attempts kept drifting toward the game-card shape.

## 픽스

Added `configs/host_opencritic-com_news_ef0b3c95.json` with `row_selector="div.mt-4 > div"` and
`row_required_selector='a[href^="/news/"]'`. Article bodies come from `div[itemprop="articleBody"]`.

Local validation: 10 posts, first article body 2620 chars.
