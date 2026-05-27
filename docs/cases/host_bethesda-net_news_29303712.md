---
slug: host_bethesda-net_news_29303712
url: https://www.bethesda.net/news/
status: "✅ handcrafted — Bethesda news config registered from rendered article links"
outcome: handcrafted
date: 2026-05-28
fix_layer: F
failure_keys: [posts_nonempty, hashed_selector]
config_strategy: playwright_html
tags: [games-us, bethesda, material-ui, selector-grounding]
---

## 무엇이 일어났나
Agentic generation copied a Material UI selector from the probe candidate and exhausted max cycles with `posts_nonempty 0건`. The probe artifact was otherwise clean: `first_article_url` was a real `/ko/article/...` URL and the rendered list contained 10 article links.

## 왜 문제인가
The copied row selector depended on generated `bnetArticle-MuiGrid-*` class combinations. A fresh runtime render can move those classes enough for a zero-row list even though the article links are present.

## 픽스
Added `configs/host_bethesda-net_news_29303712.json` with `playwright_html`, stable `a[href*='/ko/article/']` rows, and `main#_bnContent` article extraction. No `headless:false` was used.

## 일반화 후보
- 패턴: generated CSS/MUI selector copied while href prefix is stable.
- 영향: `host_bethesda-net_news_29303712`, `host_bethesda-net_news_c5aa2960`, Epic CSS-in-JS cases.
- fix layer 판단: A/D/F hit through prompt guidance, richer grounding feedback, and mixed article JSON support.
- 별도 worktree 필요성: no; bounded prompt/validation/strategy patch included in this task.

## 회귀 검증
Local smoke: list 5; first article body 12106 chars.

