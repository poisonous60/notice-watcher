---
slug: naver-blog_ghangth_5a895e5f
url: https://blog.naver.com/ghangth/221299970841
status: ✅ 자동 (recognizer 신규 — naver-blog, naver-blog_dhyana69 와 같은 PR 에서 동시 풀림)
outcome: handcrafted
date: 2026-05-16
requested_by: poi23619
failure_keys: [posts_nonempty, list_url_none, candidates_zero]
fix_layer: F
config_strategy: handwritten
adapters_changed: [naver_blog]
engine_files_touched: [adapters/naver_blog.py, adapters/__init__.py, engine/recognizers/naver_blog.py]
tags: [naver-blog, rss-feed, known-platform-recognizer, article-url-given]
---

## 무엇이 일어났나
사용자가 `blog.naver.com/ghangth/221299970841` (네이버 블로그 개별 글 URL — desktop path 형식). 자동 파이프 retry 실패 — `[FAIL] posts_nonempty: 0건`. last_config 는 `playwright_html` + `PostList.naver?blogId={board}` + `wait_selector=div.post_item` — PostList.naver 가 SPA 라 `div.post_item` 영원히 안 뜸. probe 의 `list_url=None`, `candidates=0`, `first_article=''` (글페이지 자체).

자세한 픽스 내용·후속 후보는 [`naver-blog_dhyana69_85ae2dd0`](naver-blog_dhyana69_85ae2dd0.md) 와 같음 (같은 PR 에서 두 케이스 동시 풀림). 이 case 는 PATTERN `/<blogId>/<logNo>` (path 형식 글 URL) 매칭 검증.

## 회귀 검증
- `register.py "https://blog.naver.com/ghangth/221299970841"` → recognize hit `naver-blog` builder, `blog_id=ghangth`, baseline 30건. 본문 3140 chars (RSS 첫 글: "5.16과 전두환").
