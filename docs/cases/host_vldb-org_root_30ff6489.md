---
slug: host_vldb-org_root_30ff6489
url: https://vldb.org/
status: 🧩 수동 config — root landing 대신 Latest News 정적 목록 사용
outcome: handcrafted
date: 2026-05-21
failure_keys: [posts_nonempty, root_landing_page, row_selector_wrong]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [academic, vldb, static-html, latest-news]
requested_by: batch
---

## 무엇이 일어났나

사용자 전달 기준 `https://vldb.org/` 는 자동 config 에서 `posts_nonempty=0` 이었다. 로컬에는 해당
`.FAILED.json` 과 probe 산출물이 없어 `last_feedback`/`diagnosis` 원문은 재인용하지 못했다.

직접 확인 결과 root page 는 VLDB Endowment landing page 이며, root navigation menu 를 scraping 하면
컨퍼런스/저널/시상 링크가 섞인다. 반면 root 의 `Latest News` 링크인 `https://vldb.org/news.html` 은
정적 `div.content li` 3건을 제공한다.

## 픽스

`configs/host_vldb-org_root_30ff6489.json` 생성. 원래 `_source_url` 은 root 로 보존하고, list URL은
`https://vldb.org/news.html` 로 둔다. `post_id` 는 `newslist/<slug>.html`, `title` 은 li text,
`url` 은 news article href 를 절대 URL 로 변환한다.

## Track B 검토

- **2a 인식기 — X.** VLDB 단일 사이트 source-url 보정이다.
- **2b article-url — X.** 첫 글 오인이 아니라 root landing 과 실제 news list 의 분리다.
- **2c/2d probe/generate — 보류.** root landing 에서 `Latest News` follow-up 을 추론하는 개선은 allow-list 밖이다.
- **2e 수동 config — O.** 확인 가능한 notice-like list 는 `/news.html` 이다.

일반화 안 되는 이유: root navigation에는 여러 목록이 섞여 있어 자동으로 어느 목록이 사용자 의도인지 정하기 어렵다.

## 회귀 검증

- `preflight: miss — host_vldb-org_root_30ff6489` (로컬 config/probe/FAILED 산출물 없음)
- `validate_config` → OK.
- `make_adapter(...).fetch_list(page_size=5)` → 3건, first post `new_trustees_2022`.
- 첫 글 `fetch_article()` body length 814.

