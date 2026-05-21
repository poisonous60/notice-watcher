---
slug: host_crunchyroll-com_news_02fd4569
url: https://www.crunchyroll.com/news
status: 🔧 손 config (httpx_json) — Crunchyroll News 공개 JSON API 사용
outcome: handcrafted
date: 2026-05-22
requested_by: batch
failure_keys: [posts_nonempty]
fix_layer: none
config_strategy: httpx_json
adapters_changed: []
engine_files_touched: []
tags: [crunchyroll, news-api, nextjs-shell, httpx-json]
---

## 무엇이 일어났나

`[FAIL] posts_nonempty: 0건`.

자동 생성은 `playwright_html`로 `main article` 또는 `a[href*='/news/']` 계열 selector를 반복 시도했지만, probe 산출물의 `list.html`은 Next.js shell과 loader 중심이라 실제 기사 row가 없었다. `feed_candidates`에는 `https://www.crunchyroll.com/rss`가 잡혔지만, 확인 결과 이 피드는 "Latest Crunchyroll Videos"이고 `/news` 게시판의 뉴스 피드가 아니어서 채택하지 않았다.

HAR에는 `https://cr-news-api-service.prd.crunchyrollsvc.com/v1/en-US/stories?slug=%2F` 호출이 보였고, 같은 서비스의 `/stories/search?page_size=...&page=...&order_by=newest`가 최신 뉴스 기사 목록을 반환했다.

preflight: b-hit — 실패 이후 `engine/probe` 관련 commit(`27ed350`, `5665fa8`)이 있었고 `register.py --reuse-probe "https://www.crunchyroll.com/news"`를 재시도했지만 동일하게 `posts_nonempty`로 실패했다.

## 무엇을 바꿨나 (fix layer: none — 단발 수동 config)

**`configs/host_crunchyroll-com_news_02fd4569.json`** — `httpx_json`.

- `list.url_template`: Crunchyroll News public API `/v1/en-US/stories/search?order_by=newest`
- `post_id`: API `slug`
- `title`: `content.headline`
- `url`: `https://www.crunchyroll.com/news/{post_id}`
- `published_at`: `content.created_at`
- `category`: `content.category`
- `summary`: `content.lead`
- `cover_image`: `content.thumbnail.filename`
- `article`: `/v1/en-US/stories?slug={post_id}` → `story.content.seo.description`

## 회귀 검증

- 스키마 OK.
- `make_adapter` 손 실행: list 3건, 첫 글 `latest/2026/5/21/nezumikozo-jirokichi-rintaro-anime-short-film-stream-youtube`, body 263 chars.
- `register.py --config configs/host_crunchyroll-com_news_02fd4569.json` → baseline 20건 등록.
- `probe_smoke.py --stage 3 --stage 5` → PASS 1063, FAIL 0, WARN 0, SKIP 0.

## 일반화 안 함 이유

Crunchyroll 전용 공개 API 경로를 직접 쓰는 단일 host/board 수동 config다. probe가 본 RSS 후보는 실제 뉴스가 아니라 영상 피드였고, 현재 케이스 하나만으로 `feed_candidates` 선택 규칙이나 generic recognizer를 넓히면 오탐 위험이 더 크다.
