---
slug: host_enisa-europa-eu_news_9ab433c4
url: https://www.enisa.europa.eu/news
status: 🧩 수동 config — ENISA static news cards로 baseline 14건 등록
outcome: handcrafted
date: 2026-05-24
failure_keys: [posts_nonempty, nav_first_article, filter_url]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [govedu, enisa, news, html]
---

## 무엇이 일어났나

preflight: miss — 로컬 FAILED/probe artifact 가 없었다. 사용자 전달 실패 요지는 `posts_nonempty 0` 과 first_article 이 `/news?f[0]=topics...` filter URL 로 잡힌 것이다.

라이브 HTML 에서는 실제 news rows 가 `div.featured-items` 와 `div.publications-item` 으로 정적으로 존재하고, 필터 링크와 주제 링크가 같은 페이지에 섞여 있다.

## 픽스

`configs/host_enisa-europa-eu_news_9ab433c4.json` 을 `httpx_html` 로 작성했다.

- 목록: featured/publication cards
- required: `h3 a[href^='/news/']`
- ID/URL/title/date/type/summary: card 내부 h3/time/type/description
- 본문: article page 의 `article`, fallback `main`

robots.txt 는 `/news` 를 허용하고 Crawl-Delay 는 없다.

## 회귀 검증

- `python scripts/register.py --config configs/host_enisa-europa-eu_news_9ab433c4.json` → baseline 14건, rc=0
- `make_adapter` 손실행 → list 14건, 첫 글 body 9740자

## 트랙 B 검토

- 2a 인식기: X. ENISA Drupal card 구조 단일 사이트.
- 2b `--article-url`: X. filter URL 오탐은 목록 selector scope 문제.
- 2c/2d probe/prompt: 보류. filter link 배제는 일반 후보지만 이번 수정은 사이트 class 에 한정.
- 2e 수동 config: O.

일반화 안 되는 이유: row classes and filter layout are ENISA-specific.
