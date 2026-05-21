---
slug: host_hoyolab-com_circles_f742739b
url: https://www.hoyolab.com/circles/8/0/official?lang=ko-kr
status: ✅ 수동 config (bbs-api-os getNewsList gids=8, 15건 baseline)
outcome: improved
date: 2026-05-19
fix_layer: F
failure_keys: [board_shape_gate_rejected, gen_fail_posts_nonempty, spa_no_article_links]
config_strategy: httpx_json
adapters_changed: []
engine_files_touched: []
tags: [hoyolab, zenless-zone-zero, bbs-api-os, spa, nuxt, getNewsList]
requested_by: poisonous60
---

HoYoLAB 젠레스존제로 (ZZZ). 같은 패턴 `host_hoyolab-com_circles_41251f69.md` (gids=2) + gids 만 8 로 변경.

차이: 첫 batch 에서 gen_fail posts_nonempty (probe 가 article cards 잡았지만 LLM 이 selector 박을 때 user profile 링크 추출 → posts_nonempty=0). 수동 config 으로 우회.

상세: `infra_catalog_batch_rev4_2026-05-19.md`.
