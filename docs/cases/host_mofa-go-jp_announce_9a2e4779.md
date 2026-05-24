---
slug: host_mofa-go-jp_announce_9a2e4779
url: https://www.mofa.go.jp/announce/index.html
status: registered via current official MOFA English press release index
outcome: handcrafted
date: 2026-05-24
fix_layer: none
failure_keys: [capability_blocked, cloudflare, deprecated-entry, rss_unavailable]
config_strategy: httpx_html
tags: [batch-2026-05-21-govedu, anti-bot, static-html]
---

preflight: miss - local FAILED/probe artifacts were absent; no existing config.

RSS discovery found no usable `/announce.rdf`, `/announce/index.rdf`, or `/rss/announce.xml` feed. The submitted `/announce/index.html` is an archive/category entry and `/announce/announce/index.html` is blocked to plain httpx. The current official English press release index, `/press/release/index.html`, is static HTML and reachable with plain httpx.

Branch: rejected RSS, then static HTTP replacement. `configs/host_mofa-go-jp_announce_9a2e4779.json` polls `main ul.link-list > li > a[href*='/press/release/pressite_']` and fetches the linked release body from `div#main`.

Root-cause: capability_blocked/deprecated announce entry plus no official announce RSS. A current same-site official press-release index avoids Cloudflare-style blocking without adding stealth code.

Track-B: not generalized. This is a MOFA-specific current-index remap, not a new generic anti-bot capability.

Regression note: impact is limited to this new config. No shared files were changed.
