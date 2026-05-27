---
slug: host_bethesda-net_news_c5aa2960
url: https://bethesda.net/news/
status: "✅ handcrafted — non-www Bethesda news config registered"
outcome: handcrafted
date: 2026-05-28
fix_layer: F
failure_keys: [posts_nonempty, hashed_selector]
config_strategy: playwright_html
tags: [games-us, bethesda, material-ui, selector-grounding]
---

## 무엇이 일어났나
The non-www Bethesda URL failed the same way as the www URL: agentic attempts ended in `posts_nonempty: 0건` despite probe evidence showing a real `/ko/article/...` list.

## 왜 문제인가
The last generated config still depended on generated Material UI classes. The stable signal was the article href prefix, not the class stack.

## 픽스
Added `configs/host_bethesda-net_news_c5aa2960.json` with `playwright_html`, `a[href*='/ko/article/']` rows, and article content from `main#_bnContent`.

## 일반화 후보
- 패턴: same host family duplicated as www/non-www and both failed by selector grounding.
- 영향: both Bethesda slugs in this batch.
- fix layer 판단: A/D prompt and validation feedback now point the agent away from copied generated selectors.
- 별도 worktree 필요성: no.

## 회귀 검증
Local smoke: list 5; first article body 12106 chars.

