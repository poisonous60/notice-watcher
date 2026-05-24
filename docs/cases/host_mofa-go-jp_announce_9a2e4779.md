---
slug: host_mofa-go-jp_announce_9a2e4779
url: https://www.mofa.go.jp/announce/index.html
status: capability_blocked (Cloudflare) — RSS unavailable, HTML remap policy-rejected
outcome: no_change
date: 2026-05-24
fix_layer: none
failure_keys: [capability_blocked, cloudflare, rss_unavailable]
tags: [batch-2026-05-21-govedu, anti-bot, policy-no-remap]
---

preflight: miss

Branch: capability_blocked (rc=5/cloudflare). Cloudflare blocks plain httpx on `/announce/index.html`. RSS auto-discovery on same host (announce.rdf, /rss/announce.xml etc) returned no usable feed.

Codex W2C initially proposed remap to `/press/release/index.html` (different HTML page, same host). Policy = RSS-only remap (slug anchored to original URL). HTML remap to a *different* page risks slug drift and content scope change (announce ≠ press release). Config reverted.

Slug left in Later/capability_blocked bucket. Future fix paths:
1. Discover proper announce RSS (none currently)
2. Stealth playwright that defeats Cloudflare on `/announce/index.html`
3. User re-watch with current canonical URL (e.g. `/press/release/index.html`) — new slug, new subscription
