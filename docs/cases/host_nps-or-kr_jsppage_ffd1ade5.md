---
slug: host_nps-or-kr_jsppage_ffd1ade5
url: https://www.nps.or.kr/jsppage/main.jsp
status: registered via current NPS homepage notice links
outcome: handcrafted
date: 2026-05-24
fix_layer: none
failure_keys: [capability_blocked, entry_blocked, deprecated-entry]
config_strategy: httpx_html
tags: [batch-2026-05-21-govedu, static-html, korean-public-site]
---

preflight: miss - local FAILED/probe artifacts were absent; no existing config.

The submitted `/jsppage/main.jsp` endpoint now returns an error page. Official search results and live fetches show the current NPS homepage is `/main.do`, which contains recent `새소식` entries as static anchors with `fnc_newsInfoDetail(...)` arguments.

Branch: RSS unavailable, static HTTP replacement. `configs/host_nps-or-kr_jsppage_ffd1ade5.json` polls `/main.do`, selects only `BS20240137` notice anchors, extracts `pstId` from the JavaScript href, and builds the current detail URL template.

Root-cause: stale JSP entry URL, not a reusable anti-bot bypass. The current official homepage is enough for a low-volume notice baseline.

Track-B: not generalized. The JavaScript href pattern is NPS-specific.

Regression note: impact is limited to this new config. No shared engine or recognizer files changed.
