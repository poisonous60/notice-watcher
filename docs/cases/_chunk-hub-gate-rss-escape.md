---
slug: _chunk-hub-gate-rss-escape
url: https://www.wheresyoured.at/
status: validated RSS feed now escapes heterogeneous hub gate
outcome: improved
date: 2026-05-25
fix_layer: F
failure_keys: [gate_reject, heterogeneous_hub, validated_rss_feed]
config_strategy: rss
adapters_changed: []
engine_files_touched: [scripts/register.py]
tags: [rss, hub-gate, substack, false-negative]
---

## What Happened

The heterogeneous hub post-mortem gate in `scripts/register.py` rejected root pages when
the static HTML had no clean same-host article cluster. That is useful for real hub/SPA
roots, but it was too broad for sites where probe already found a fetch-validated RSS or
Atom feed with `item_count > 0`.

Observed batch examples include `https://www.wheresyoured.at/` and Substack/custom-domain
newsletter roots such as `notboring.co`, `flowstate.fm`, `densediscovery.com`,
`racket.news`, `foreignexchanges.news`, `drilled.media`, `hackernewsletter.com`,
`javascriptweekly.com`, `devopsweekly.com`, and `androidweekly.net`.

## Root Cause

`_heterogeneous_hub_check` only evaluated HTML repeating clusters. A page with valid RSS
could still hit `clean article cluster 0` and become rc=3 `gate_reject`, even though RSS
was a valid board source.

## Fix

Added an F-layer escape in `scripts/register.py`: if `digest.feed_candidates` contains a
fetch-validated RSS/Atom candidate with a positive item count, `_heterogeneous_hub_check`
returns `None` before applying the HTML cluster dominance gate.

The check reuses `engine.digest._validated_feed_candidates` so the criteria match the
existing digest-level feed semantics:

- `validated is True`
- `item_count > 0`
- `root_tag` is `rss` or `feed`

## Regression Verification

Added `tests/test_hub_gate_rss_escape.py`:

- validated RSS candidate + HTML cluster 0 shape escapes with `None`
- invalid/feed-like candidate with the same HTML cluster 0 shape still returns the
  existing `clean article cluster 0` reject reason

## Impact

This is a generic register-flow fix, not a site-specific allow-list. RSS remains subject
to fetch validation; empty feeds and HTML shells do not bypass the hub gate.
