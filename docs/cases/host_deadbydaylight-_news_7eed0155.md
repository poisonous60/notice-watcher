---
slug: host_deadbydaylight-_news_7eed0155
url: https://deadbydaylight.com/news/
status: "✅ handcrafted — Dead by Daylight rendered list plus Gatsby article JSON"
outcome: handcrafted
date: 2026-05-28
fix_layer: F
failure_keys: [article_body_len, article_fetch_kind, json_api]
config_strategy: playwright_html
tags: [games-us, deadbydaylight, gatsby, page-data]
---

## 무엇이 일어났나
Agentic found the Gatsby `/page-data/news/page-data.json` API but generated invalid or ineffective article fetch settings (`fetch_kind: httpx_html`, JSON decode errors, and short body failures).

## 왜 문제인가
The page-data list contains the full archive in an order that does not match the rendered news page, while the per-article page-data endpoint has the real body. A rendered list plus JSON article fetch matches the site behavior.

## 픽스
Added `configs/host_deadbydaylight-_news_7eed0155.json` with `playwright_html` rows from `div.article-card:has(a[href^='/news/'])` and article JSON from `/page-data/news/{post_id}/page-data.json`.

## 일반화 후보
- 패턴: Gatsby list/article page-data exists, but list API ordering can differ from rendered board order.
- 영향: Gatsby sites with archive payloads and per-article page-data bodies.
- fix layer 판단: F hit via mixed rendered list + JSON article support; A prompt now explicitly names Gatsby page-data JSON.
- 별도 worktree 필요성: no.

## 회귀 검증
Local smoke: list 5; first article body 2799 chars.

