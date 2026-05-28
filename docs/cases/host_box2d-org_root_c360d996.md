---
slug: host_box2d-org_root_c360d996
url: https://box2d.org/
status: improved — RSS fallback registered baseline 22 (Hugo landing, real posts at /posts/)
outcome: improved
date: 2026-05-28
failure_keys: [posts_nonempty, probe_grounding_list_row_selector, validated_feed_available]
fix_layer: F
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: [scripts/register.py]
tags: [rss-fallback, hugo, indie-game-dev, batch]
requested_by: batch
---

## Summary

Hugo landing page at `/` with menu links only (real posts at `/posts/`). Gate passed because validated RSS feed `https://box2d.org/index.xml` (22 items) + `site_kind=hybrid+high`. LLM tried HTML row extraction on `ul.menu__inner > li` (nav menu) → 0 posts → gen_fail.

F-layer RSS-fallback override (see [`_generic_rss_fallback_override`](_generic_rss_fallback_override.md)) registered baseline 22 from `index.xml` after gen_fail.

## Track B

- F layer hit — generic RSS fallback override in `scripts/register.py`. No per-site config writing; mechanism is `_generic_rss_fallback_override`.
