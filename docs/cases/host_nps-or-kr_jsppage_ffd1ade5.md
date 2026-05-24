---
slug: host_nps-or-kr_jsppage_ffd1ade5
url: https://www.nps.or.kr/jsppage/main.jsp
status: capability_blocked (entry_blocked) — RSS unavailable, HTML remap policy-rejected
outcome: no_change
date: 2026-05-24
fix_layer: none
failure_keys: [capability_blocked, entry_blocked, rss_unavailable]
tags: [batch-2026-05-21-govedu, anti-bot, policy-no-remap]
---

preflight: miss

Branch: capability_blocked (rc=5/entry_blocked). Original `/jsppage/main.jsp` entry now returns error from plain httpx. RSS auto-discovery on same host returned no usable feed.

Codex W2C initially proposed remap to `/main.do` (different HTML page, same host). Policy = RSS-only remap. HTML remap to a different page risks slug drift. Config reverted.

Slug left in Later/capability_blocked bucket. Future fix paths:
1. Discover proper NPS RSS (none currently)
2. Stealth playwright that defeats entry block on `/jsppage/main.jsp`
3. User re-watch with current canonical URL (`/main.do`) — new slug, new subscription
