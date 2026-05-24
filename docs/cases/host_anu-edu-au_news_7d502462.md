---
slug: host_anu-edu-au_news_7d502462
url: https://www.anu.edu.au/news
status: 🔧 손 config (httpx_html) — newsroom root has a small Latest news block; probe picked the All news navigation card
outcome: handcrafted
date: 2026-05-24
failure_keys: [posts_nonempty, first_article_nav]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [govedu-wave-1a, anu, drupal, newsroom]
---

## 무엇이 일어났나
Wave 1A `gen_fail`: `[FAIL] posts_nonempty: 0건`. The stale probe note said `first_article_url=/news/all-news?field_story_category...`, which is the All news/search navigation route rather than one of the visible Latest news articles on the requested `/news` page.

## 진단 근거
- `preflight: miss` — no existing `configs/host_anu-edu-au_news_7d502462.json`, no recognizer match, and this worktree had no `output/poll_state` or `output/probe` artifact to reuse.
- `diagnosis.verdict`: unavailable locally; user-supplied tail was `posts_nonempty 0?`.
- Failure guide branch: `posts_nonempty` with a nav/search first article maps to `docs/config 자동생성 실패 케이스.md` 2a.
- Raw page cross-check: the requested `/news` page has a bounded `Latest news` block with four real `/news/all-news/<slug>` article links before the All news/search cards.
- Prior-case cross-check: `rg "first_article_nav|posts_nonempty|ANU|newsroom" docs/cases` did not show a reusable ANU/Drupal recognizer.
- Robots/polite check: `/robots.txt` does not disallow `/news` or `/news/all-news` and has no Crawl-Delay. Engine default 3-6s host sleep remains in force.

## 무엇을 바꿨나
`configs/host_anu-edu-au_news_7d502462.json` keeps `list.url_template` on the requested `https://www.anu.edu.au/news` page and narrows rows to the top `Latest news` layout only. Article bodies are extracted from `main article`.

## 회귀 검증
- Schema validation: OK.
- make_adapter smoke: list 4 rows; first article body 11303 chars.
- `register.py --config`: passed and registered the config locally.

## 일반화 안 함 이유
The selector depends on ANU's newsroom landing layout. It should not become a generic Drupal rule because the same `.views-element-container` pattern also appears on non-article cards lower on the page.

## 트랙 B 후보
없음. Track-B deferred: no generic change proposed; this is a site-specific selector narrowing fix.
