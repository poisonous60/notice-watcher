---
slug: host_dblp-org_db_e427dd1d
url: https://dblp.org/db/conf/
status: 🧩 수동 config — DBLP new issues/volumes RSS 사용
outcome: handcrafted
date: 2026-05-21
failure_keys: [posts_nonempty, rss_feed_available]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [academic, dblp, rss-fallback, conference-index]
requested_by: batch
---

## 무엇이 일어났나

사용자 전달 기준 `https://dblp.org/db/conf/` 는 batch `gen_fail(rc=1)` 이며 feed 후보는
`https://dblp.org/feed/new.rss` 였다. 로컬에는 해당 `.FAILED.json` 과 probe 산출물이 없어
`triage.py show` 기반 원문 진단은 재현하지 못했다.

직접 확인 결과 DBLP feed 는 200 응답, `channel > item` 896건을 제공한다. 샘플은 `APCCAS 2025`,
link `https://dblp.org/db/conf/apccas/apccas2025.html`, guid
`https://dblp.org/db/conf/apccas/apccas2025`, pubDate `Tue, 19 May 2026 01:00:00 +0200` 이다.

## 픽스

`configs/host_dblp-org_db_e427dd1d.json` 생성. `strategy=httpx_html`, `row_selector=channel > item`,
`post_id` 는 guid 의 `/db/...` 경로를 `_` 로 정규화한다. title/link/pubDate/description 은 RSS에서
직접 추출한다.

## Track B 검토

- **2a 인식기 — X.** DBLP 전용 RSS rescue 이며 이번 allow-list 밖 recognizer 변경은 하지 않는다.
- **2b article-url — X.** 목록 index 대신 feed source 선택 문제다.
- **2c/2d probe/generate — 보류.** RSS 후보 선택 일반화는 Track B 후보지만 이번 작업은 config-only다.
- **2e 수동 config — O.** 기존 XML parsing strategy 로 안정적으로 해결된다.

일반화 안 되는 이유: `/db/conf/` 의 사용자 의도는 conference index 이고, DBLP의 new feed는 사이트 고유
대체 source 이다.

## 회귀 검증

- `preflight: miss — host_dblp-org_db_e427dd1d` (로컬 config/probe/FAILED 산출물 없음)
- `validate_config` → OK.
- `make_adapter(...).fetch_list(page_size=5)` → 5건, first post `conf_apccas_apccas2025`.
- 첫 글 `fetch_article()` body length 1691875.

