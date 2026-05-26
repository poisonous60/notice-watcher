---
slug: host_3dmgame-com_root_40371626
url: https://www.3dmgame.com/
status: ✅ registered by hand config after batch retry gen_fail
outcome: fixed
date: 2026-05-26
failure_keys: [gen_fail, validator_timeout, mixed_homepage_rows]
fix_layer: config
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [games-batch, 3dmgame, hand-config]
requested_by: round-2-retry-batch-20260526
---

## 조사 결과

Retry jobs `3183` and `3194` left the root URL in gen_fail/rejected split: `/news/` was correctly rejected, while the
root page still had a valid news stream but generated attempts failed validation. The post-timeout retry showed
structured `validate_internal_timeout_25s`, not a raw tool hang.

The homepage mixes several blocks. `li > div.lis` with required `a.tex[href*="/news/"]` isolates the current news list.

## 픽스

Added `configs/host_3dmgame-com_root_40371626.json`; article content uses `div.content`.

Local validation: 30 posts, first article body 25357 chars.
