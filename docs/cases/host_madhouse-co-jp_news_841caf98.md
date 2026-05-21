---
slug: host_madhouse-co-jp_news_841caf98
url: https://www.madhouse.co.jp/news/
status: ✅ 수동 config 등록 (playwright_html, baseline 4건)
outcome: handcrafted
date: 2026-05-21
requested_by: batch
failure_keys: [posts_nonempty, json_api_article_body_len, published_at_iso]
fix_layer: none
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [madhouse, hand-config, playwright-html, nuxt]
---

## 무엇이 일어났나

`[FAIL] posts_nonempty: 0건`.

정적 HTML 목록에는 실제 글 row 가 없고 header/footer nav 만 반복 후보로 잡혔다. probe 는
`traffic_json_api_candidates=1` 로 `https://madhouse.co.jp/cms-data/json/news.json?...`
를 찾았지만, 자동 생성은 `httpx_json` 시도에서 본문 fetch 와 날짜 변환을 동시에 틀렸다.

- 목록 JSON 은 `id`, `title`, `category_label`, `display_date`, `display_datetime` 만 제공한다.
- 글 본문은 개별 글 HTML 의 `script#unit04-news-data` JSON island 에 있고, 브라우저 렌더 후
  `.wysiwyg` 로 주입된다.
- 자동 시도 2는 `display_date` 에 `T00:00:00+09:00` 를 붙인 뒤 ISO 파싱하려 해
  `2026/04/01T00:00:00+09:00` 형태가 되어 `published_at_iso` 를 실패했다.

## 무엇을 바꿨나

단일 사이트 수동 config 를 추가했다.

- `configs/host_madhouse-co-jp_news_841caf98.json`
- strategy: `playwright_html`
- list: `https://www.madhouse.co.jp/news/`, `li.news-item`
- post_id: `/news/{id}/` 의 `{id}`
- article: `https://www.madhouse.co.jp/news/{post_id}/`, `.wysiwyg`
- title/date/category enrich: `.news-article__title`, `.news-article__date`, `.news-article__label`

## 회귀 검증

- 스키마 OK.
- `make_adapter` 손 실행:
  - list 4건
  - 첫 글 `zwy5jxs0hx9qbtnh`
  - body 232 chars
- `python scripts/register.py --config "configs/host_madhouse-co-jp_news_841caf98.json"` PASS
  - baseline 4건

## 트랙 B 검토

- 2a 인식기: X — Madhouse 단일 host 의 Nuxt news 구조다. 재사용할 플랫폼 신호가 없다.
- 2b first_article_url 교정: X — probe first article 은 nav 링크 `/news` 였고, 개별 글 URL 교정만으로
  JSON 목록과 본문 JSON island 양쪽 문제를 해결하지 못한다.
- 2c/2d probe/schema/prompt: 보류 — 누적 query 에서 `posts_nonempty` 와 `JSON API` 는
  `track_b_trigger=true` 이지만, 이번 케이스의 작동 해법은 특정 사이트의 렌더 DOM selector 다.
  generic probe/engine 변경은 단일 slug 허용 범위를 넘고 blast radius 가 커서 적용하지 않았다.
- 2e 수동 config: 적용 — `playwright_html` 기존 어휘만으로 목록과 본문을 모두 안정 추출한다.

일반화 안 되는 이유: 목록 JSON 과 개별 글의 `script#unit04-news-data` 조합은 이 Nuxt 사이트의
구현 세부사항이다. 새 recognizer 나 probe 휴리스틱으로 넓히기에는 같은 CMS 반복 신호가 없다.
