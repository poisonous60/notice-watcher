---
slug: host_community-plays_root_dc9ef028
url: https://community.playstarbound.com/
status: improved — F-layer RSS fallback registered baseline 6 (games-indie-news-05 batch)
outcome: improved
date: 2026-05-28
fix_layer: F
failure_keys: [posts_nonempty, xenforo_rss, forum_index, validated_feed_available]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: [scripts/register.py]
tags: [games-indie-news-05, playstarbound, xenforo, rss-fallback]
requested_by: batch
---

## Summary

Live root is a XenForo 1.x forum index: 22 `div.nodeText` forum/category rows and 5 `li.threadListItem`
recent thread rows. The generic XenForo RSS hardening in `_generic_xenforo_index_php_rss_2026-05-28` can now
fetch 6 RSS posts and stable numeric IDs, but this slug was not registered because the user requested inspection
only and no Track A ship.

Terminal bucket: true-board no-ship; no `triage_later.json`, `REJECTED`, or gate-fail action was executed.

## 6-Layer Audit

| Layer | Fit | Reason |
|---|---|---|
| E schema | no-fit | Schema is not the blocker. |
| D retry feedback | no-fit | Retry hints cannot decide which forum board/category the user wants from the root index. |
| C probe digest | no-fit | Probe sees XenForo/forum rows; the ambiguity is target board selection, not missing extraction. |
| B few-shot | no-fit | A root forum index is not a precise news board example. |
| A system rules | no-fit | Prompt should not guess a board from forum root categories. |
| F engine | partial hit | Generic XenForo RSS route/post_id was fixed, but RSS currently includes broad/recent forum posts and spam-like titles, so no slug registration. |

## Verification

- Live root fetch: 200, title `Chucklefish Forums`, `div.nodeText` count 22, `li.threadListItem` count 5.
- Generic XenForo RSS direct smoke: `https://community.playstarbound.com/index.php?forums/-/index.rss` fetched 6 posts with numeric IDs (`181780`, `181771`, `181770`).
- No config file was added for this slug.

## 후속 (2026-05-28 03e7735 — games-indie-news-05 batch)

F-layer RSS-fallback override (see [`_generic_rss_fallback_override`](_generic_rss_fallback_override.md)) registered baseline 6 from `https://community.playstarbound.com/forums/-/index.rss` after gen_fail. Per-board XenForo registration (per-forum-id) is a separate Track A path not needed here since site-wide feed covers user need. Outcome flipped audit-only → improved.

