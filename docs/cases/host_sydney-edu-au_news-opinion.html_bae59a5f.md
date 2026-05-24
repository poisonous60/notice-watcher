---
slug: host_sydney-edu-au_news-opinion.html_bae59a5f
url: https://www.sydney.edu.au/news-opinion.html
status: 🧩 수동 config — Sydney latest-news cards로 baseline 2건 등록
outcome: handcrafted
date: 2026-05-24
failure_keys: [posts_nonempty, nav_first_article, archive_link]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [govedu, sydney, news, html]
---

## 무엇이 일어났나

preflight: miss — 로컬 FAILED/probe artifact 가 없었다. 사용자 전달 실패 요지는 `posts_nonempty 0` 과 first_article 이 `/news-opinion/news/2026.html` 연도 archive 로 잡힌 것이다.

제출 URL은 `https://www.sydney.edu.au/news-opinion/latest-news.html` 로 redirect 된다. 실제 최신 뉴스 카드는 HTML의 `div.m-card--featured-news > div[data-link]` 에 `data-link`, `data-title`, `data-description` 으로 들어 있다. 연도 archive 링크는 목록 row 가 아니다.

## 픽스

`configs/host_sydney-edu-au_news-opinion.html_bae59a5f.json` 을 `httpx_html` 로 작성했다.

- 목록: latest-news 카드 `div[data-link]`
- ID: `/news-opinion/news/YYYY/MM/DD/<slug>.html`
- 본문: article page 의 `div.text`, fallback `main`

robots.txt 는 latest-news/article 경로를 허용하고 Crawl-Delay 는 없다.

## 회귀 검증

- `python scripts/register.py --config configs/host_sydney-edu-au_news-opinion.html_bae59a5f.json` → baseline 2건, rc=0
- `make_adapter` 손실행 → list 2건, 첫 글 body 3465자

## 트랙 B 검토

- 2a 인식기: X. Sydney AEM card 구조 단일 사이트.
- 2b `--article-url`: X. 첫 글 교정으로도 archive 링크를 목록 row 로 고른 문제가 남는다.
- 2c/2d probe/prompt: 보류. data-* 카드 추출 일반화 후보는 있지만 현 단계에서는 단일 config 로 해결.
- 2e 수동 config: O.

일반화 안 되는 이유: 카드 attribute 이름과 latest-news redirect 가 Sydney 고유 구조다.
