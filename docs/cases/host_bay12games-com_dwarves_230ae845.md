---
slug: host_bay12games-com_dwarves_230ae845
url: https://www.bay12games.com/dwarves/
status: "✅ handcrafted — Bay 12 inline devlog list"
outcome: handcrafted
date: 2026-05-28
fix_layer: none
failure_keys: [posts_nonempty, post_id_stable_shape, inline_devlog]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [games-indie-01, bay12, inline-devlog, track-a]
requested_by: poisonous60
---

## Summary

Live page has 246 `li.dev_progress[id]` rows. Each row is the article: date span, author image title, and
inline text. There is no separate article URL, so the config uses the row `id` as post_id and emits fragment
URLs such as `https://www.bay12games.com/dwarves/#2026-05-20`.

Ship evidence: user explicitly requested this batch to ship three sites, including Bay 12 dwarves, after
Track B-first audit.

## 6-Layer Audit

| Layer | Fit | Reason |
|---|---|---|
| E schema | no-fit | Existing `template`, `regex_extract`, and `body_empty_acceptable` express the shape. |
| D retry feedback | no-fit | Retry could say post_id is URL-shaped, but cannot infer fragment URLs for inline rows. |
| C probe digest | no-fit | Inline devlog is visible in live HTML; adding a broad inline-article heuristic from one site would be speculative. |
| B few-shot | no-fit | One Bay 12-style inline devlog is not enough to promote a few-shot. |
| A system rules | no-fit | A prompt rule for `li.dev_progress` would be site-specific. |
| F engine | no-fit | No new strategy or recognizer is required. |

## Verification

- `python scripts/register.py --config configs/host_bay12games-com_dwarves_230ae845.json`: rc=0, baseline 30.
- First rows included `2026-05-20` and `R2026-05-20`; titles were non-empty.
- Article body is intentionally list-only with `article.body_empty_acceptable=true`.

