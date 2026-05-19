---
slug: host_hoyolab-com_circles_5051fb8a
url: https://www.hoyolab.com/circles/6/0/official?lang=ko-kr
status: ✅ 손-config (bbs-api-os getNewsList gids=6, 15건 baseline)
outcome: improved
date: 2026-05-19
fix_layer: F
failure_keys: [board_shape_gate_rejected, spa_no_article_links]
config_strategy: httpx_json
adapters_changed: []
engine_files_touched: []
tags: [hoyolab, honkai-star-rail, bbs-api-os, spa, nuxt, getNewsList]
requested_by: poisonous60
---

HoYoLAB 스타레일. 같은 패턴 `host_hoyolab-com_circles_41251f69.md` (gids=2) + gids 만 6 으로 변경.

차이: 첫 batch 에선 BUG (subprocess_timeout, SW assertion crash). SW launch arg fix 후 정상 → 손-config 박음.

상세: `infra_catalog_batch_rev4_2026-05-19.md`.
