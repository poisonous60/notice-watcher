---
slug: host_hoyolab-com_circles_41251f69
url: https://www.hoyolab.com/circles/2/0/official?lang=ko-kr
status: ✅ 수동 config (bbs-api-os getNewsList gids=2, 15건 baseline)
outcome: improved
date: 2026-05-19
fix_layer: F
failure_keys: [board_shape_gate_rejected, spa_no_article_links]
config_strategy: httpx_json
adapters_changed: []
engine_files_touched: []
tags: [hoyolab, genshin, bbs-api-os, spa, nuxt, getNewsList]
requested_by: poisonous60
---

## 무엇이 일어났나

catalog batch run 2026-05-19 첫 run 에서 board_shape gate_reject. probe 가 정적 HTML 에서 `mhy-article-card-wrapper` 15건 잡지만 cards 의 `href` 가 `/accountCenter?id=...` (user profile) 만 — article 링크 X. SPA route 가 JS click 으로 처리.

## 픽스

handwritten config. 비공식 `bbs-api-os.hoyolab.com/community/post/wapi/getNewsList?gids=2&type=1` REST endpoint 사용 (HAR XHR 캡처로 발견). `x-rpc-language: ko-kr` 헤더 필수. data.list[].post 안에 post_id/subject/created_at(unixtime s)/cover. URL pattern `https://www.hoyolab.com/article/{post_id}`. article body 도 `getPostFull?post_id={post_id}` 의 data.post.post.content.

## 함정

- url_template 에 `{page_size}` 직접 substitute X — pagination engine 이 size_param=page_size 로 query 에 append. 첫 commit 후 register.py KeyError 'page_size' 로 fail → 즉시 fix.

## 관련

`circles_6` (스타레일, gids=6) + `circles_8` (ZZZ, gids=8) 동일 패턴 — `host_hoyolab-com_circles_5051fb8a.md` / `host_hoyolab-com_circles_f742739b.md`.

상세: `infra_catalog_batch_rev4_2026-05-19.md`.
