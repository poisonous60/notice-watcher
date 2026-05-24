---
slug: host_u-tokyo-ac-jp_en_b730db58
url: https://www.u-tokyo.ac.jp/en/whatsnew/
status: registered via official UTokyo press RSS/RDF feed
outcome: handcrafted
date: 2026-05-24
fix_layer: none
failure_keys: [capability_blocked, entry_blocked, rss_fallback]
config_strategy: httpx_html
tags: [batch-2026-05-21-govedu, rss, anti-bot, deprecated-entry]
---

preflight: miss - local FAILED/probe artifacts were absent; no existing config.

The submitted `/en/whatsnew/` URL is not usable from this environment: plain httpx returned a tiny 404 body and curl_cffi hit a connection reset. The current official English UTokyo press page at `/focus/en/press/` is reachable and exposes an RSS/RDF link, `/focus/en/press/feed.rdf`.

Branch: RSS. `configs/host_u-tokyo-ac-jp_en_b730db58.json` polls the official RDF feed with `row_selector=item`, extracts `post_id` from the press article URL, and fetches article body from the linked press page `article` element.

Root-cause: stale/deprecated entry URL plus capability_blocked style fetch behavior on the submitted path. RSS avoids the blocked/dead entry path without adding stealth code.

Track-B: not generalized. This is a single-host official feed choice; no probe/generate/recognizer files were changed.

Regression note: impact is limited to this new config. No existing config uses this slug or URL.
