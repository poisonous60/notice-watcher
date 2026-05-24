---
slug: host_news-cornell-ed_root_5ab391ee
url: https://news.cornell.edu/
status: 🔧 손 config (playwright_html) — browser-rendered/latest-news selector works; httpx gets 403 from Cornell
outcome: handcrafted
date: 2026-05-24
failure_keys: [posts_nonempty, httpx_403, first_article_ok]
fix_layer: none
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [govedu-wave-1a, cornell, drupal, playwright]
---

## 무엇이 일어났나
Wave 1A `gen_fail`: `[FAIL] posts_nonempty: 0건`. The stale probe note had a plausible article URL under `/stories/2026/05/...`, so the first-article heuristic was not the main fault. The site blocks this repo's `httpx` client with 403 while normal browser navigation succeeds.

## 진단 근거
- `preflight: miss` — no existing `configs/host_news-cornell-ed_root_5ab391ee.json`, no recognizer match, and this worktree had no `output/poll_state` or `output/probe` artifact to reuse.
- `diagnosis.verdict`: unavailable locally; user-supplied tail was `posts_nonempty 0?` with a plausible Cornell story URL.
- Failure guide branch: `posts_nonempty` plus client-specific 403 maps to `playwright_html` rather than selector-only `httpx_html`.
- Raw page cross-check: browser/request-style fetch sees `#hp-latest-news .story-xs` rows; `httpx` receives 403 for the same URL.
- Prior-case cross-check: `rg "httpx_403|playwright_html|Cornell|posts_nonempty" docs/cases` did not show a reusable Cornell recognizer.
- Robots/polite check: `/robots.txt` allows `/` and story paths; no Crawl-Delay was found. Engine default 3-6s host sleep remains in force.

## 무엇을 바꿨나
`configs/host_news-cornell-ed_root_5ab391ee.json` uses `playwright_html` for the root page, waits for `#hp-latest-news .story-xs a[href]`, and extracts rows from the Latest News block. Article bodies are extracted from `article .field--name-body`.

## 회귀 검증
- Schema validation: OK.
- make_adapter smoke: list 3 rows in the focused smoke; first article body 9434 chars.
- `register.py --config`: passed and registered the config locally.

## 일반화 안 함 이유
This is a client-fingerprint/capability workaround for one host, not a reusable selector or recognizer improvement. Adding a generic Drupal-to-Playwright rule would over-escalate many static Drupal sites that work with `httpx_html`.

## 트랙 B 후보
없음. Track-B deferred: if more university Drupal roots show `httpx` 403 with browser success, consider a capability classifier, but this single case stays site-specific.
