---
slug: host_randomascii-wor_root_f74fd8ea
url: https://randomascii.wordpress.com/
status: improved — RSS fallback registered baseline 10 (WordPress.com hosted, /wp-json 404)
outcome: improved
date: 2026-05-28
failure_keys: [posts_nonempty, probe_grounding_list_row_selector, post_id_unique, validated_feed_available]
fix_layer: F
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: [scripts/register.py]
tags: [rss-fallback, wordpress, wordpress-com-hosted, indie-game-dev, batch]
requested_by: batch
---

## Summary

`wordpress.com` hosted site (not self-hosted WP). `detect_wordpress_platform` correctly identifies it via `generator=WordPress.com` + `wp-content`/`wp-includes` markers, but the derived `https://randomascii.wordpress.com/wp-json/wp/v2/posts` returns 404 — WordPress.com sites expose REST at `public-api.wordpress.com/wp-json/?rest_route=/sites/<host>` instead. LLM HTML attempts hit `channel>item` (XML structure in HTML strategy) → 0 rows → gen_fail.

Validated RSS `https://randomascii.wordpress.com/feed/` (10 items) used by F-layer fallback (see [`_generic_rss_fallback_override`](_generic_rss_fallback_override.md)). GUID with `?p=<id>` normalized to stable numeric IDs by the fallback config's post_id chain.

## Track B

- F layer hit — generic RSS fallback override. WordPress.com hosted REST endpoint mismatch is a separate known issue (`detect_wordpress_platform` assumes self-hosted `/wp-json` path); RSS feed exists for both hosted and self-hosted so fallback handles both.

## Follow-up candidate (deferred)

WordPress.com hosted sites could use `public-api.wordpress.com/wp-json/?rest_route=/sites/<host>` recognizer for richer data than RSS (full content vs RSS summary). Not needed for this slug — RSS coverage sufficient. Add to `_deferred_heuristics.md` if pattern repeats in future batches.
