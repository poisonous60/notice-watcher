---
slug: host_ec-europa-eu_commission_8fc8d9c8
url: https://ec.europa.eu/commission/presscorner/home/en
status: ✅ 수동 config 등록 준비 (Press Corner RSS endpoint)
outcome: handcrafted
date: 2026-05-24
fix_layer: none
failure_keys: [probe_timeout, spa_shell, rss_endpoint]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [gen-fail, batch-2026-05-21-govedu, rss, european-commission]
---

## 진단

preflight: miss — local `output/probe` / `output/poll_state` artifacts absent, existing config absent, recognizer None.

`https://ec.europa.eu/commission/presscorner/home/en` is an Angular shell. The failed batch tail was `probe_timeout 120s`, so extending Playwright wait time would keep the slow path without improving the board model.

Live endpoint check found `https://ec.europa.eu/commission/presscorner/api/rss?language=en` returning RSS items with `guid`, `title`, `link`, `pubDate`, and `description`.

## 변경

`configs/host_ec-europa-eu_commission_8fc8d9c8.json` uses `httpx_html` over the public RSS endpoint. Article body extraction uses `meta[name="description"]` on the canonical Press Corner detail page, which provides more than 100 characters for the first item.

## 검증

- `make_adapter` live check: 5 posts, first post `speech_26_977`, first article body length 200.
- `python scripts/register.py --config "configs/host_ec-europa-eu_commission_8fc8d9c8.json"` PASS, baseline 10 posts.
- `python scripts/probe_smoke.py --stage 3 --stage 5` PASS.

## 트랙 B

No recognizer or generic engine change in this batch. This is a single-site RSS remap, not a reusable platform family yet.
