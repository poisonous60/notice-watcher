---
slug: host_epicgames-com_news_4655a152
url: https://www.epicgames.com/news/
status: "✅ handcrafted — Epic news config registered without hashed selectors"
outcome: handcrafted
date: 2026-05-28
fix_layer: F
failure_keys: [probe_grounding_list_row_selector, hashed_selector, article_json_api]
config_strategy: playwright_html
tags: [games-us, epicgames, akamai, css-in-js, selector-grounding]
---

## 무엇이 일어났나
The generated config already tried `a[href^='/blog/']`, but validation failed with `probe_grounding_list_row_selector 0 nodes` and retries still centered on the probe's hashed `ul.css-* > li.css-*` selector family.

## 왜 문제인가
The stable row is the `li` containing a `/blog/` link. The article body should come from the captured JSON API, because direct browser article navigation can be challenged.

## 픽스
Added `configs/host_epicgames-com_news_4655a152.json` with `playwright_html` list extraction, `li:has(a[href^='/blog/'])`, and JSON article extraction through `store-content-ipv4.ak.epicgames.com`.

## 일반화 후보
- 패턴: same Epic platform as Store URL with hashed list classes and article JSON API.
- 영향: both Epic slugs.
- fix layer 판단: A/D/F hit.
- 별도 worktree 필요성: no.

## 회귀 검증
Local smoke: list 5; first article body 5508 chars.

