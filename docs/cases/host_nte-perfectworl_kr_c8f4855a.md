---
slug: host_nte-perfectworl_kr_c8f4855a
url: https://nte.perfectworld.com/kr/article/news/index.html
status: 🔧 손 config (작동중, baseline 3, httpx_html)
date: 2026-05-15
requested_by: poi23619
failure_keys: [article_body_len]
config_strategy: httpx_html
fix_pr: e670930
---

## 무엇이 일어났나
`[FAIL] article_body_len`. list 추출은 정상(3건)이었으나 LLM 이 article.url_template 을 `…/gamebroad/{post_id_year}{post_id_month}{post_id_day}/{post_id}.html` 로 만들었고 — 엔진 transform 에 그런 placeholder 없음 → 그대로 URL 에 들어가 `%7Bpost_id_year%7D…` 인코딩 404. list 의 `url` 필드는 이미 정상 추출되었는데(`…/gamebroad/20260512/262140.html`) `article.url_template` 이 그걸 덮어 fetch_article 4회 전부 404.

## 무엇을 바꿨나
`article.url_template` 제거 → `httpx_html.article_url_for` 가 `post.url` 로 폴백. 나머지 selector 는 그대로(`div.articleContent` 본문, `h1.articleTitle` enrich title, `p.articleDate` `%Y.%m.%d`).

## 회귀 검증
스모크: 목록 3건·본문 4924자.
