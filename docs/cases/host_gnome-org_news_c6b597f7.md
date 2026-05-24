---
slug: host_gnome-org_news_c6b597f7
url: https://www.gnome.org/news/
status: no_change - GNOME news and feed endpoints remain baseline_blocked from this environment
outcome: no_change
date: 2026-05-24
fix_layer: none
failure_keys: [capability_blocked, baseline_blocked, rss_unavailable]
config_strategy: none
tags: [batch-2026-05-21-govedu, rss, baseline-blocked, no-change]
---

preflight: miss - local FAILED/probe artifacts were absent; no existing config.

RSS/Atom discovery checked the official GNOME news paths and adjacent project feeds: `/news/`, `/news/feed/`, `/feed/`, `/news/rss.xml`, `thisweek.gnome.org/*`, and `planet.gnome.org/*`. In this environment all tested GNOME-hosted endpoints returned the same 503 baseline block page. Playwright with stealth also returned 503 for `https://www.gnome.org/news/` and `https://www.gnome.org/feed/`. Jina reader was also not usable: it only reproduced the target 503/502 error text, not a parseable news/feed list.

Branch: RSS attempted, stealth attempted, rejected. No config was written because any config targeting these endpoints would fail baseline registration and would make smoke checks worse.

Root-cause: site/network-level baseline_blocked for GNOME infrastructure from this environment, not a selector or feed discovery problem.

Track-B: not generalized. This needs a runtime capability change or a different network path; the current task explicitly forbids adding code or deployment work.

Regression note: no config/engine change for this slug. The case records the failed RSS/stealth investigation only.
