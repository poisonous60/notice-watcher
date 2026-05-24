---
slug: host_canada-ca_en_a89e35ea
url: https://www.canada.ca/en/news.html
status: 🧩 수동 config — Canada.ca advanced news results로 baseline 10건 등록
outcome: handcrafted
date: 2026-05-24
failure_keys: [posts_nonempty, nav_first_article, landing_page]
fix_layer: none
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [govedu, canada, news, playwright]
---

## 무엇이 일어났나

preflight: miss — 로컬 FAILED/probe artifact 가 없었다. 사용자 전달 실패 요지는 `posts_nonempty 0` 과 first_article 이 `/en/services/jobs.html` 같은 nav 로 잡힌 것이다.

`/en/news.html` 은 뉴스 서비스 landing page 이며 게시글 목록이 아니다. 실제 최신 Government of Canada news rows 는 `https://www.canada.ca/en/news/advanced-news-search/news-results.html` 에서 렌더된 `main article.item` 으로 나온다.

## 픽스

`configs/host_canada-ca_en_a89e35ea.json` 을 `playwright_html` 로 작성했다.

- 목록: advanced news search `main article.item`
- wait: `main article.item h3 a`
- ID/URL/title/date/department/category/summary: row 내부 h3/time/p
- 본문: article page 의 `main`

Canada.ca robots.txt 는 로컬 httpx 로는 timeout 이 났지만, 대상은 공개 news search/article 페이지이고 config 는 5-6초 sleep 을 둔다.

## 회귀 검증

- `python scripts/register.py --config configs/host_canada-ca_en_a89e35ea.json` → baseline 10건, rc=0
- `make_adapter` 손실행 → list 10건, 첫 글 body 4426자

## 트랙 B 검토

- 2a 인식기: X. Canada.ca landing → advanced search remap 은 사이트별.
- 2b `--article-url`: X. root cause 는 입력 URL 이 게시판이 아닌 landing page 인 점.
- 2c/2d probe/prompt: 보류. landing page nav 오탐은 일반 이슈지만 이 config 는 단일 public search page 로 제한.
- 2e 수동 config: O.

일반화 안 되는 이유: advanced-news-search URL 과 `article.item` row 구조가 Canada.ca 고유다.
