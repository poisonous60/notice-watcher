---
slug: host_us-forums-blizz_en_895a75b6
url: https://us.forums.blizzard.com/en/wow/latest
status: ✅ 수동 config (Discourse `/latest.json` REST 직결, 30건 baseline)
outcome: improved
date: 2026-05-19
fix_layer: F
failure_keys: [posts_nonempty, board_shape_gate_passed_no_extraction]
config_strategy: httpx_json
adapters_changed: []
engine_files_touched: []
tags: [discourse, blizzard, forum, latest-json, known-platform-pattern]
requested_by: poisonous60
---

## 무엇이 일어났나

catalog batch run 2026-05-19 첫 run 에서 gen_fail (subkind=posts_nonempty). probe 가 forum.blizzard.com 의 articles 못 추출 — Ember.js SPA, 정적 HTML 에 row 0개.

## 픽스

handwritten config. Discourse 의 well-known `<board>/latest.json` REST endpoint 사용 — `topic_list.topics[]` 에 title/id/slug/created_at/last_poster_username/category_id. URL pattern `/t/{post_id}`. article body 도 `/t/{post_id}.json` 의 `post_stream.posts[0].cooked`.

## 일반화 후보

Discourse 인식기 (`engine/recognizers/discourse.py`) — `<meta name="generator" content="Discourse">` 또는 `/latest.json` 200 응답 확인 패턴. 미박음 (지금 catalog 안 Discourse 사이트는 Blizzard 1개 — over-engineering).

상세: `infra_catalog_batch_rev4_2026-05-19.md`.
