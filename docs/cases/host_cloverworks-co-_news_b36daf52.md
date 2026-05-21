---
slug: host_cloverworks-co-_news_b36daf52
url: https://www.cloverworks.co.jp/news/
status: ✅ 손 config + probe 개선 (작동중, baseline 20, httpx_html)
outcome: improved
date: 2026-05-21
requested_by: batch
failure_keys: [posts_nonempty, matches_probe_first_article]
fix_layer: C+config
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: [probe/extract.py]
tags: [cloverworks, wordpress, category-link, overlay-anchor, first-article-url]
---

## 무엇이 일어났나
`[FAIL] posts_nonempty: 0건`. 자동 생성 config 는 `ul.thumblist > li.list__item` row 자체는 맞게 골랐지만, row 안 첫 링크가 글 링크가 아니라 `/news/category/other` 카테고리 링크였다.

probe 도 같은 오인을 해서 `first_article_url=https://www.cloverworks.co.jp/news/category/other` 를 냈고, retry 가 같은 selector/strategy 를 3회 반복했다. 실제 글 URL 은 각 row 끝의 빈 overlay anchor (`https://cloverworks.co.jp/news/20260319/`) 에 있었다.

## 무엇을 바꿨나
**Track B (C)**: `probe/extract.py:html_repeating_patterns` 가 row 안의 첫 `<a>`를 무조건 sample 로 쓰지 않고, row 내부 anchor 들 중 `_article_url_score` 가 가장 높은 href 를 고르게 했다. 동시에 `_article_url_score` 의 same-site 판정을 exact host 에서 registrable domain 으로 완화해 `www.cloverworks.co.jp` 입력과 `cloverworks.co.jp` 글 URL 을 같은 사이트로 본다.

**단일 config**: `configs/host_cloverworks-co-_news_b36daf52.json`
- 목록: `ul.thumblist > li.list__item`
- 글 링크: `a[href^='https://cloverworks.co.jp/news/']` 로 카테고리 링크 제외
- post_id: `/news/<id>/`
- 본문: `.news__detail .detail__text`
- 날짜: `%Y.%m.%d` → `+09:00`

## 일반화 효과
정적 목록 row 안에 taxonomy/category/tag 링크가 먼저 나오고 실제 글 링크가 뒤쪽 overlay anchor 로 있는 사이트에서, probe 의 `sample_url`/`first_article_url` 이 카테고리 페이지로 틀어지는 실패를 줄인다. 새 selector 문법이나 adapter 를 추가하지 않고 기존 article URL 점수화를 row 내부 링크 선택에도 재사용했다.

## 회귀 검증
- 스키마 OK.
- `html_repeating_patterns` 수동 확인: `sample_url=https://cloverworks.co.jp/news/20260319/`, `first_article_url=https://cloverworks.co.jp/news/20260319/`.
- `make_adapter` 손 실행: list 5건, 첫 글 `20260319`, body 4182 chars.
- `python scripts/register.py --config configs/host_cloverworks-co-_news_b36daf52.json` → baseline 20건.
- `python scripts/probe_smoke.py --stage 5` → 80 파일, 872 케이스, 0 FAIL, coverage 36/36.

## 영향 범위
`html_repeating_patterns` 의 `sample_url` 선택만 바뀐다. 기존 단일 링크 row 는 그대로이고, 여러 링크 row 에서만 글 URL 점수가 높은 href 로 바뀐다. 같은 사이트의 www/non-www 변형도 같은 registrable domain 으로만 완화했다.
