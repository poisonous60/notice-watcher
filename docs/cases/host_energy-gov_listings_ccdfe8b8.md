---
slug: host_energy-gov_listings_ccdfe8b8
url: https://www.energy.gov/listings/energy-news
status: ✅ 수동 config 등록 준비 (Energy.gov RSS endpoint)
outcome: handcrafted
date: 2026-05-24
fix_layer: none
failure_keys: [probe_timeout, drupal_listing, rss_endpoint]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [gen-fail, batch-2026-05-21-govedu, rss, energy-gov]
---

## 진단

preflight: miss — local `output/probe` / `output/poll_state` artifacts absent, existing config absent, recognizer None.

The failed batch tail was `probe_timeout 120s`. The listing page is Drupal and exposes an RSS link, so the lower-risk fix is to avoid Playwright and poll the feed directly.

Live endpoint check found `https://www.energy.gov/rss/energygov/2193718` returning RSS items for Energy News. The listing page also links this feed as `RSS`.

## 변경

`configs/host_energy-gov_listings_ccdfe8b8.json` uses `httpx_html` over the RSS endpoint. RSS item links are canonical Energy.gov article URLs; article body extraction uses `main article` with `article` fallback.

## 검증

- `make_adapter` live check: 5 posts, first article body length 3870.
- `python scripts/register.py --config "configs/host_energy-gov_listings_ccdfe8b8.json"` PASS, baseline 10 posts.
- `python scripts/probe_smoke.py --stage 3 --stage 5` PASS.

## 트랙 B

No shared recognizer added. This is a one-site feed remap; if more Drupal government listing pages expose `/rss/<site>/<id>` feeds, a recognizer can be considered later.
