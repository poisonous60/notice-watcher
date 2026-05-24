---
slug: host_govinfo-gov_root_2458d525
url: https://www.govinfo.gov/
status: 🔧 손 config (httpx_html, RSS-backed Features list) — root probe picked browse/navigation links before the real feed-backed feature rows
outcome: handcrafted
date: 2026-05-24
failure_keys: [posts_nonempty, first_article_nav]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [govedu-wave-1a, govinfo, rss, drupal]
---

## 무엇이 일어났나
Wave 1A `gen_fail`: `[FAIL] posts_nonempty: 0건`. The stale probe note said `first_article_url=/app/collection/budget`, which is a Browse/collection navigation link from the GovInfo root, not an article row.

## 진단 근거
- `preflight: miss` — no existing `configs/host_govinfo-gov_root_2458d525.json`, no recognizer match, and this worktree had no `output/poll_state` or `output/probe` artifact to reuse.
- `diagnosis.verdict`: unavailable locally; user-supplied tail was `posts_nonempty 0?`.
- Failure guide branch: `posts_nonempty` with nav/sidebar first article maps to the selector/list-source branch in `docs/config 자동생성 실패 케이스.md` 2a.
- Raw page cross-check: the root exposes a feed link `/rss.xml`; that feed contains the same recent GovInfo feature/news items and avoids the root Browse menu links.
- Prior-case cross-check: `rg "posts_nonempty|first_article_nav|nav" docs/cases` showed this as the known wrong-first-link family, but not a reusable platform recognizer.
- Robots/polite check: `/robots.txt` allows the feed path; no Crawl-Delay was present. Engine default 3-6s host sleep remains in force.

## 무엇을 바꿨나
`configs/host_govinfo-gov_root_2458d525.json` uses `httpx_html` against `https://www.govinfo.gov/rss.xml`, which is linked from the requested root page. Rows are RSS `item` entries; article bodies are fetched from the item links with `#block-bootstrap-fdsys-content article .field--name-body.field__item`.

## 회귀 검증
- Schema validation: OK.
- make_adapter smoke: list 5 rows; first article body 7138 chars.
- `register.py --config`: passed and registered the config locally.

## 일반화 안 함 이유
This is a single Drupal/GovInfo root-feed mapping. It does not justify a generic root-page-to-feed recognizer because feed semantics vary by host and can drift from the requested list.

## 트랙 B 후보
없음. Track-B deferred: no generic change proposed; this is a site-specific feed-backed config.
