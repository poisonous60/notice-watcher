---
slug: host_producthunt-com_feed_51ccf15a
url: https://www.producthunt.com/feed
status: ✅ 등록 (Product Hunt Atom feed 사용, 본문은 list-only)
outcome: handcrafted
date: 2026-05-21
fix_layer: none
failure_keys: [posts_nonempty, rss_feed_available, atom_feed, body_empty_acceptable]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [producthunt, atom, feed, list-only, batch-2026-05-21-misc]
---

## 무엇이 일어났나

`https://www.producthunt.com/feed` 는 Next.js 화면이 아니라 Atom feed 자체다. probe 도
`feed_candidates=2건` 을 잡았지만, 자동 생성은 `entry`/`feed > entry` selector 방향에서도
검증상 `posts_nonempty: 0건` 으로 실패했다.

저장된 `list.html` 은 Chromium XML viewer wrapper 안에 Atom XML 이 들어 있었고, 실제 httpx
응답은 `application/atom+xml` 이다. 엔진의 `parse_html_or_xml` 은 원본 XML 응답이면 `entry`
selector 를 정상 처리한다.

## 조치

`configs/host_producthunt-com_feed_51ccf15a.json` 을 Atom XML config 로 작성했다.

- `list.url_template: https://www.producthunt.com/feed`
- `row_selector: entry`
- `post_id` 는 Atom `id` 의 `Post/<id>` 에서 추출
- `title`, `published_at`, `author > name`, `summary(content)`, `link[rel="alternate"]` 추출
- product detail page 는 403 을 반환할 수 있어 `article.skip_status: [403]` 과
  `body_empty_acceptable: true` 로 list-only 등록

## 검증

- config schema validation PASS.
- `register.py --config configs/host_producthunt-com_feed_51ccf15a.json` PASS, baseline 30건.
- 첫 product page 는 403 이지만 skip 처리되어 본문 0자 경고만 남고 등록 완료.

## 트랙 B

Product Hunt 는 feed URL 자체가 입력된 케이스라 단일 config 가 가장 작다. generic RSS/Atom
direct-feed recognizer 는 기존 Google News/Steam처럼 플랫폼별 semantics 가 있는 feed 와 충돌할
수 있어 이번 변경에서는 Statuspage direct feed 로만 제한했다.
