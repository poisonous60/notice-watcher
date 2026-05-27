---
slug: host_store-epicgames_news_16cc8b8f
url: https://store.epicgames.com/news/
status: "✅ handcrafted — Epic Store news list via Playwright, article via JSON API"
outcome: handcrafted
date: 2026-05-28
fix_layer: F
failure_keys: [probe_grounding_list_row_selector, hashed_selector, article_json_api]
config_strategy: playwright_html
tags: [games-us, epicgames, akamai, css-in-js, selector-grounding]
---

## 무엇이 일어났나
Agentic retries used Emotion `css-*` selectors and failed with zero row matches. A direct HEAD check returned 403, so the list needs browser rendering, while the article body is available from `store-content-ipv4.ak.epicgames.com`.

## 왜 문제인가
The article browser route lands on an Akamai challenge in runtime, but the probe HAR had a clean JSON body endpoint. The old strategy code did not honor `article.fetch_kind:"json"` for Playwright-backed list configs.

## 픽스
Added `configs/host_store-epicgames_news_16cc8b8f.json` using `li:has(a[href^='/blog/'])` for rendered rows and the `store-content` JSON endpoint for article bodies. Updated HTML strategies so `article.fetch_kind:"json"` delegates to the JSON article parser.

## 일반화 후보
- 패턴: CSS-in-JS list shell plus separate article JSON body API.
- 영향: both Epic slugs.
- fix layer 판단: F hit, because mixed list strategy + JSON article fetch is engine behavior.
- 별도 worktree 필요성: no.

## 회귀 검증
Local smoke: list 5; first article body 5508 chars.

