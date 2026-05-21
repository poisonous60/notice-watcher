---
slug: host_lidenfilms-jp_news_ac5488a7
url: https://www.lidenfilms.jp/news/
status: ✅ 등록 (WordPress RSS news feed, baseline 10건; 본문은 list-only)
outcome: handcrafted
date: 2026-05-21
requested_by: batch
failure_keys: [post_id_unique, post_id_stable_shape, rss_feed_available, body_empty_acceptable]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [lidenfilms, wordpress-rss, external-links, list-only]
---

## 무엇이 일어났나

`[FAIL] post_id_unique: 중복 1건` + `[FAIL] post_id_stable_shape`. 정적 HTML 목록 자체는 정상이고
`div.newsList_list > article.topNews_listitem.newsItem._extertnal` 로 10건이 잡힌다. 다만 행 링크가
개별 뉴스 글이 아니라 작품 페이지(`/works/...`)를 가리키며, 같은 작품 페이지에 여러 뉴스가 붙어 href
단독 `post_id` 가 중복된다.

probe 는 `feed_candidates=2건` (`/rss`, `/feed`) 을 이미 잡았고, live 확인상 `/news/feed/` 도 같은
뉴스 항목을 RSS item 으로 제공한다. RSS `<guid>` 의 `?p=<id>` 값이 가장 안정적인 신규 판정 키다.

## 무엇을 바꿨나

`configs/host_lidenfilms-jp_news_ac5488a7.json` 을 RSS XML config 로 작성했다.

- `list.url_template`: `https://www.lidenfilms.jp/news/feed/`
- `row_selector`: `item`
- `post_id`: RSS `guid` 의 `?p=<id>`
- `title`, `url`, `published_at`, `summary`: RSS item 필드
- `article.content: []`, `body_empty_acceptable: true`

## 검증

- config schema validation PASS.
- `make_adapter` 손 실행: list 10건, 첫 글 `2814`, body 0 chars.
- `register.py --config configs/host_lidenfilms-jp_news_ac5488a7.json` PASS, baseline 10건.

## 트랙 B

누적 `post_id_unique`/`post_id_stable_shape` 는 trigger=true지만, 이번 root cause 는 LIDENFILMS HTML
archive 가 작품 페이지를 재사용하는 단일 사이트 구조다. RSS 후보 신호는 이미 probe digest 에 있고,
RSS/Atom XML 파싱도 기존 엔진에서 지원한다. 범용 WordPress `/news/feed/` 승격은 custom post type,
route, content 공개 여부가 사이트별로 달라 이번 변경에서는 보류했다.
