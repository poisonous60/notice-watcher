---
slug: host_ethz-ch_en_7733150b
url: https://ethz.ch/en/news-and-events/eth-news.html
status: 🔧 손 config (httpx_html, Atom feed) — static page has an empty newsfeed container and points to an ETH feed/API source
outcome: handcrafted
date: 2026-05-24
failure_keys: [posts_nonempty, first_article_nav, js_feed_container]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [govedu-wave-1a, ethz, atom, aem]
---

## 무엇이 일어났나
Wave 1A `gen_fail`: `[FAIL] posts_nonempty: 0건`. The stale probe note said `first_article_url=/en/`, which is the ETH homepage/navigation link. The requested page's static HTML contains a `newsfeed2` component placeholder, not article rows.

## 진단 근거
- `preflight: miss` — no existing `configs/host_ethz-ch_en_7733150b.json`, no recognizer match, and this worktree had no `output/poll_state` or `output/probe` artifact to reuse.
- `diagnosis.verdict`: unavailable locally; user-supplied tail was `posts_nonempty 0?`.
- Failure guide branch: `posts_nonempty` caused by JS/feed-backed list source, matching `docs/config 자동생성 실패 케이스.md` 2a.
- Raw page cross-check: the page includes `data-api-url="/en/news-and-events/eth-news/_jcr_content/par/newsfeed2.newsfeed.FROM-TO.json"` and ETH's RSS page exposes the English ETH News Atom feed.
- Prior-case cross-check: `rg "posts_nonempty|js_feed_container|Atom|feed" docs/cases` did not show an existing ETH/AEM reusable recognizer.
- Robots/polite check: `https://ethz.ch/robots.txt` returned 404, so no path-specific disallow or Crawl-Delay was found. Engine default 3-6s host sleep remains in force.

## 무엇을 바꿨나
`configs/host_ethz-ch_en_7733150b.json` uses `httpx_html` against ETH's official Atom feed at `https://www.ethz.ch/en/news-und-veranstaltungen/eth-news/news/_jcr_content.feed.html`. Rows are `entry` elements. Article bodies are fetched from each entry link and extracted with `.content-main`.

## 회귀 검증
- Schema validation: OK.
- make_adapter smoke: list 5 rows; first article body 43945 chars.
- `register.py --config`: passed and registered the config locally.

## 일반화 안 함 이유
The AEM feed/API path is component-specific and host-specific. No generic AEM recognizer was added because that would need broader URL and component coverage than this single site proves.

## 트랙 B 후보
후보만 있음: AEM `newsfeed2` component could become a recognizer if at least two more hosts expose the same `_jcr_content/par/newsfeed2.newsfeed.FROM-TO.json` or `_jcr_content.feed.html` structure.
