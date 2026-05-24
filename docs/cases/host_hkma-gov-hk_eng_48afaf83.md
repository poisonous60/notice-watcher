---
slug: host_hkma-gov-hk_eng_48afaf83
url: https://www.hkma.gov.hk/eng/news-and-media/press-releases/
status: "ok - static HKMA press-release list registered"
outcome: handcrafted
date: 2026-05-24
fix_layer: none
failure_keys:
  - probe_timeout
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags:
  - hkma
  - press-release
---

## Root Cause

preflight: miss - `configs/host_hkma-gov-hk_eng_48afaf83.json` was absent, recognizer returned `None`, and no prompt/engine/probe/recognizer commits or uncommitted changes existed after `failed_at=2026-05-24T02:57:16.331402+00:00`.

The failed queue marker was caused by `register probe timeout: probe timeout (120s)`, not by a blocked or missing board. The pulled probe artifact still contained a usable page snapshot: the list rows are static under `#press-release-result > ul`, and the first article body is static under `.content-area .template-content-area`.

## Fix

Added a single-site `httpx_html` config:

- list rows: `#press-release-result > ul`
- row filter: only internal `/eng/news-and-media/press-releases/` article links, excluding occasional external `info.gov.hk` press rows
- article body: `.content-area .template-content-area`
- dates: `%d %B %Y` with `+08:00`

## Track B

No generic fix was added. This is not a new recognizer/engine/probe class: the relevant selectors were already visible in the artifact, and the failure key was a site-specific probe timeout rather than a repeated extraction failure pattern.

## Regression Verification

Impact surface is limited to this new config file. No shared engine, probe, prompt, schema, or recognizer files were changed, so existing configs are not expected to change behavior.

- `python scripts/register.py --config configs/host_hkma-gov-hk_eng_48afaf83.json`: PASS, baseline 9 posts, `body_empty_at_baseline=false`.
- direct `make_adapter` check: PASS, `fetch_list` returned 9 posts and first article `content_html_len=3229`.
- `python scripts/probe_smoke.py --stage 3 --stage 5`: PASS, stage 3 `209 / 209 OK`, stage 5 `955` cases with `0 FAIL`.
