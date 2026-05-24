---
slug: host_congress-gov_root_7881e0b8
url: https://www.congress.gov/
status: registered via official Congress.gov Notifications RSS
outcome: handcrafted
date: 2026-05-24
fix_layer: none
failure_keys: [capability_blocked, entry_blocked, rss_fallback]
config_strategy: httpx_html
tags: [batch-2026-05-21-govedu, rss, anti-bot]
---

preflight: miss - local FAILED/probe artifacts were absent; no existing config.

The portal root returns 403 to the local plain fetch path. Congress.gov documents official RSS subscriptions on `/get-alerts`; the `Congress.gov Notifications` feed is available at `/rss/notification.xml` and returned 25 items during live verification.

Branch: RSS. `configs/host_congress-gov_root_7881e0b8.json` uses the official notifications feed. Feed item links point to GovDelivery bulletins, so `article.body_empty_acceptable=true` keeps the registration focused on title/link/date/summary from the RSS feed instead of scraping the external bulletin body.

Root-cause: anti-bot protection on the portal root. The official RSS endpoint is the stable low-volume source.

Track-B: not generalized. Congress.gov exposes several RSS feeds, but this case only selects the root-level notifications feed for the submitted root URL.

Regression note: impact is limited to this new config. No engine or prompt behavior changed.
