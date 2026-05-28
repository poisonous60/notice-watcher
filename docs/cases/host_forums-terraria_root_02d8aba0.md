---
slug: host_forums-terraria_root_02d8aba0
url: https://forums.terraria.org/
status: "✅ handcrafted — XenForo Porta portal news"
outcome: handcrafted
date: 2026-05-28
fix_layer: none
failure_keys: [posts_nonempty, porta_article_item, xenforo_portal]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [games-indie-01, terraria, xenforo, porta, track-a]
requested_by: poisonous60
---

## Summary

Live root resolves to `https://forums.terraria.org/index.php` and exposes 20 Porta portal rows at
`div.porta-article-item`. The intended news surface is the portal article list, not the forum-wide XenForo RSS
feed. The config extracts title/url/id from `h2.block-header a`, date from `time.u-dt`, and thread body from
the first `article.message div.bbWrapper`.

Ship evidence: user explicitly requested this batch to ship three sites, including forums.terraria root, after
Track B-first audit.

## 6-Layer Audit

| Layer | Fit | Reason |
|---|---|---|
| E schema | no-fit | Existing CSS fields and HTML article content express the Porta portal. |
| D retry feedback | no-fit | The failure was row selection, not a retry-only transform issue. |
| C probe digest | no-fit | A Porta detector could be added later, but this batch has one Porta positive and no cross-site cluster. |
| B few-shot | no-fit | One Porta example is too specific for the shared few-shot set. |
| A system rules | no-fit | A prompt rule naming Porta classes would be site/plugin-specific. |
| F engine | no-fit for portal config | Generic XenForo RSS hardening landed separately, but this root needs the portal selector to preserve news semantics. |

## Verification

- `python scripts/register.py --config configs/host_forums-terraria_root_02d8aba0.json`: rc=0, baseline 20.
- First rows included `149950` / `Celebrating 15 Years of Terraria!`.
- Article selector was corrected from `article.message div.message-body div.bbWrapper` to `article.message div.bbWrapper`; rerun produced no body warning.

