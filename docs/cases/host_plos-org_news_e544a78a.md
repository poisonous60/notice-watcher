---
slug: host_plos-org_news_e544a78a
url: https://www.plos.org/news
status: 🧩 수동 config — 빈 plos.org feed 대신 공식 PLOS Blog RSS 사용
outcome: handcrafted
date: 2026-05-21
failure_keys: [posts_nonempty, rss_feed_stub, source_url_404]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [academic, plos, rss-fallback, source-url-shift]
requested_by: batch
---

## 무엇이 일어났나

사용자 전달 기준 `https://www.plos.org/news` 는 batch `gen_fail(rc=1)`, feed 후보
`https://www.plos.org/rss` 는 815 bytes 로 내용이 없는 RSS stub 이었다. 로컬에는 해당 `.FAILED.json` 과
probe 산출물이 없어 `last_feedback`/`diagnosis` 원문은 재인용하지 못했다.

직접 확인 결과 `https://www.plos.org/news` 는 현재 PLOS 404 페이지로 열리고,
`https://plos.org/feed/` 는 `channel > item` 이 0건이다. 대신 공식 PLOS Blog feed
`https://theplosblog.plos.org/feed/` 는 200 응답, `channel > item` 12건을 제공한다.

## 픽스

`configs/host_plos-org_news_e544a78a.json` 생성. 원래 `_source_url` 은 보존하되 polling source 는
`https://theplosblog.plos.org/feed/` 로 둔다. `post_id` 는 WordPress guid 의 `?p=<id>`, 나머지는
RSS `title/link/pubDate/description` 에서 추출한다.

## Track B 검토

- **2a 인식기 — X.** PLOS 고유 source-url 보정이며 범용 플랫폼 인식기로 묶기 어렵다.
- **2b article-url — X.** 목록 URL 자체가 404/stub 이다.
- **2c/2d probe/generate — 보류.** 빈 RSS와 404 source를 더 잘 분류하는 개선은 가능하지만 allow-list 밖이다.
- **2e 수동 config — O.** 운영상 유의미한 공식 PLOS announcement feed 로 수동 대체했다.

일반화 안 되는 이유: 같은 host 의 `/feed/` 가 비어 있고 실제 feed 가 별도 subdomain 에 있는 경우라 사이트별
판단이 필요하다.

## 회귀 검증

- `preflight: miss — host_plos-org_news_e544a78a` (로컬 config/probe/FAILED 산출물 없음)
- `validate_config` → OK.
- `make_adapter(...).fetch_list(page_size=5)` → 5건, first post `22731`.
- 첫 글 `fetch_article()` body length 7259.

