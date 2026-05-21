---
slug: host_shueisha-co-jp_news_02cebeef
url: https://www.shueisha.co.jp/news/
status: 🔧 손 config (httpx_json, baseline 20건) — WordPress REST news ID 사용
outcome: handcrafted
date: 2026-05-21
requested_by: batch
failure_keys: [post_id_stable_shape, matches_probe_first_article]
fix_layer: none
config_strategy: httpx_json
adapters_changed: []
engine_files_touched: []
tags: [shueisha, wordpress-rest, external-links, list-only]
---

## 무엇이 일어났나
`[FAIL] post_id_stable_shape`. 정적 HTML 목록(`ul.list-news > li`) 자체는 정상이고 본문도 외부 링크 기준으로는 fetch 가능했지만, 자동 생성 config 가 `post_id` 를 `url|published_at|title` 로 합쳤다. 제목과 구분자 때문에 stable shape 검증을 통과하지 못했다.

`[warn] matches_probe_first_article` 도 같이 떴다. probe 의 `first_article_url` 은 상단 nav 링크(`https://www.shueisha.co.jp/company/information/`)였지만, 실제 실패 원인은 목록 row selector 가 아니라 post_id 선택이었다.

## 무엇을 바꿨나 (fix layer: none — 단발 수동 config)
**`configs/host_shueisha-co-jp_news_02cebeef.json`** — `httpx_json`.

- `list.url_template`: `https://www.shueisha.co.jp/wp-json/wp/v2/news?_embed=1`
- `post_id`: WordPress REST `id`
- `title`: `title.rendered`
- `url`: REST `link`
- `published_at`: REST `date` (`+09:00`)
- `category`: `_embedded.wp:term[0][0].name`
- `cover_image`: `_embedded.wp:featuredmedia[0].source_url`
- `article`: REST item endpoint, `body_empty_acceptable=true`

HTML archive 의 링크는 외부 캠페인 사이트를 직접 가리키고, 같은 외부 URL 이 여러 행에 반복되는 경우가 있어 href 단독 post_id 는 `post_id_unique` 를 깬다. 공개 REST API 의 news id 가 이 사이트에서 가장 안정적인 신규 판정 키다.

## 회귀 검증
- 스키마 OK.
- `make_adapter` 손 실행: list 10건, 첫 글 `33420`, body 0 chars.
- `register.py --config configs/host_shueisha-co-jp_news_02cebeef.json` → baseline 20건, 본문 없음 경고(제목·URL 알림).

## 일반화 안 함 이유
WordPress REST API 활용은 일반 패턴이지만, public REST route 이름(`news`), category taxonomy(`cat_news`), content 공개 여부가 사이트별로 다르다. 이번 변경은 Shueisha 단일 board config 로 제한했다.
