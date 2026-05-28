---
slug: host_megacrit-com_news_4cc63275
url: https://megacrit.com/news/
status: "✅ handcrafted — Mega Crit Hugo news cards"
outcome: handcrafted
date: 2026-05-28
fix_layer: none
failure_keys: [title_nonempty, article_card, hugo_news]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [games-indie-01, megacrit, hugo, news-card, track-a]
requested_by: poisonous60
---

## Summary

Live page exposes 32 `article.news-card` rows. The title is in `h2.entry-title a`; `div.entry-content` is often
empty on the list page, which explains the generator's `title_nonempty` failure when it confused summary/content
with title fields. The config extracts article IDs from `/news/<slug>/` and fetches body HTML from the article
page `div.entry-content`.

Ship evidence: user explicitly requested this batch to ship three sites, including Mega Crit news, after
Track B-first audit.

## 6-Layer Audit

| Layer | Fit | Reason |
|---|---|---|
| E schema | no-fit | Existing CSS fields and date transforms express the Hugo cards. |
| D retry feedback | no-fit | `title_nonempty` feedback is already explicit; the issue was selector choice. |
| C probe digest | no-fit | Probe already has the rows; no missing signal was required. |
| B few-shot | no-fit | Hugo `news-card` is plausible but only one live positive in this batch; defer until a cluster forms. |
| A system rules | no-fit | The system prompt already says to inspect row HTML and avoid empty summary/content fields. |
| F engine | no-fit | No new engine behavior is needed. |

## Verification

- `python scripts/register.py --config configs/host_megacrit-com_news_4cc63275.json`: rc=0, baseline 30.
- First rows included `The Neowsletter - May 2026`, `The Neowsletter - April 2026`, and `Slay the Spire Board Game Downfall Expansion Kickstarter Liv`.
- Date parsing handles both abbreviated and full month names.

