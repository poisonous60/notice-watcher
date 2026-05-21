---
slug: host_gkids-com_news_9f98bf89
url: https://www.gkids.com/news/
status: 🔧 손 config (httpx_json, baseline 20건) — WordPress REST posts API 사용
outcome: handcrafted
date: 2026-05-21
requested_by: batch
failure_keys: [article_body_len]
fix_layer: none
config_strategy: httpx_json
adapters_changed: []
engine_files_touched: []
tags: [gkids, wordpress-rest, article-json, httpx-json]
---

## 무엇이 일어났나
`[FAIL] article_body_len: post_id=6258 0자 (<100 — content selector 의심)`.

자동 생성 config 는 HTML 목록(`div.archive-grid#results > article.news-card`)에서 WordPress post id 를 잘 뽑았지만, 본문을 `article.fetch_kind:"json"` + `https://gkids.com/wp-json/wp/v2/posts/{post_id}` 로 지정한 상태에서 0자로 검증 실패했다.

실제 REST item 응답의 `content.rendered` 는 비어 있지 않았다. 원인은 사이트 차단이 아니라 현재 `httpx_html` 전략의 article fetch 경로가 `article.fetch_kind:"json"` 을 보지 않고 HTML 파서로 처리하는 구조와 맞물린 실패였다.

## 무엇을 바꿨나 (fix layer: none — 단발 수동 config)
**`configs/host_gkids-com_news_9f98bf89.json`** — `httpx_json`.

- `list.url_template`: `https://gkids.com/wp-json/wp/v2/posts?_embed=1`
- `post_id`: WordPress REST `id`
- `title`: `title.rendered`
- `url`: REST `link`
- `published_at`: REST `date_gmt` (`Z`)
- `category`: `_embedded.wp:term[0][0].name`
- `summary`: `excerpt.rendered`
- `cover_image`: `_embedded.wp:featuredmedia[0].source_url`
- `article`: `https://gkids.com/wp-json/wp/v2/posts/{post_id}` → `content.rendered`

## 회귀 검증
- 스키마 OK.
- `make_adapter` 손 실행: list 10건, 첫 글 `6258`, body 5432 chars.
- `register.py --config configs/host_gkids-com_news_9f98bf89.json` → baseline 20건 등록.

## 일반화 안 함 이유
WordPress REST posts archive 자체는 일반 패턴이지만, 이번 요청은 단일 slug 처리 범위라 전역 recognizer/engine 변경은 하지 않았다.

Track B 후보: `httpx_html` 목록 + `article.fetch_kind:"json"` 조합을 engine 이 직접 지원하면, 이번 자동 생성 config 같은 형태가 그대로 통과할 수 있다. 다만 이는 `engine/strategies/httpx_html.py` 공용 동작 변경이라 별도 승인 후 다루는 편이 안전하다.
