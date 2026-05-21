---
slug: host_slashdot-org_root_778af9dd
url: https://slashdot.org/
status: ✅ 등록 (Slashdot RSS 사용)
outcome: handcrafted
date: 2026-05-21
fix_layer: none
failure_keys: [posts_nonempty, rss_feed_available]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [slashdot, rss, feed, batch-2026-05-21-misc]
---

## 무엇이 일어났나

root HTML 에는 `#firehoselist > article...` 반복 후보가 있었지만, 직전 자동 config 는
`posts_nonempty: 0건` 으로 실패했다. `feed_candidates.json` 의 head alternate 는
`https://rss.slashdot.org/Slashdot/slashdotMain` 을 가리켰고, 직접 확인한
`https://slashdot.org/index.rss` 는 RSS 1.0/RDF feed 로 최신 story 15건을 제공했다.

## 조치

`configs/host_slashdot-org_root_778af9dd.json` 을 RSS XML config 로 작성했다.

- `list.url_template: https://slashdot.org/index.rss`
- `row_selector: item`
- `post_id` 는 `link` 에서 query/fragment 제거
- `title`, `published_at(date)`, `author(creator)`, `category(subject)`, `summary(description)` 추출
- article page 본문은 `div.body div.p` 로 보강하되, feed summary 만으로도 baseline 가능하게
  `body_empty_acceptable` 을 켰다.

## 검증

- config schema validation PASS.
- `register.py --config configs/host_slashdot-org_root_778af9dd.json` PASS, baseline 15건.
- 첫 글 본문 fetch: 2233 chars.

## 트랙 B

Slashdot 단일 사이트 RSS config 로 충분하다. 일반 RSS feed recognizer 는 URL만으로 사이트별
board/품질 정책을 과하게 넓힐 수 있어 이번 변경에 포함하지 않았다.
