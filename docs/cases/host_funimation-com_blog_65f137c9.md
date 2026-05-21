---
slug: host_funimation-com_blog_65f137c9
url: https://www.funimation.com/blog/
status: 🔧 손 config (httpx_json) — Funimation blog remap to Crunchyroll News API
outcome: handcrafted
date: 2026-05-22
requested_by: batch
failure_keys: [posts_nonempty]
fix_layer: none
config_strategy: httpx_json
adapters_changed: []
engine_files_touched: []
tags: [funimation, crunchyroll, news-api, remap, nextjs-shell, httpx-json]
---

## 무엇이 일어났나

`[FAIL] posts_nonempty: 0건`.

`https://www.funimation.com/blog/`는 현재 `301 Location: https://www.crunchyroll.com/news`로 이동한다. probe의 rendered `list.html`도 `og:url=https://www.crunchyroll.com/news`, `Crunchyroll News` title, Next.js loader shell만 담고 있었고, 정적 HTML 후보는 `head > link`, `head > meta`, `head > script`, `body > script`뿐이었다. 자동 생성은 `playwright_html` selector를 반복했지만 실제 기사 row가 DOM에 없어 같은 실패로 끝났다.

preflight: b-hit — 실패 이후 영향 영역 commit(`27ed350`, `5665fa8`)이 있었고 `register.py --reuse-probe "https://www.funimation.com/blog/"`를 재시도했지만 동일하게 `posts_nonempty`로 실패했다.

screen-out: none — soft-404가 아니라 Funimation URL이 Crunchyroll News로 정상 remap된 케이스다.

## 무엇을 바꿨나 (fix layer: none — 단발 수동 config)

**`configs/host_funimation-com_blog_65f137c9.json`** — `httpx_json`.

- `_source_url`: 원 요청 URL `https://www.funimation.com/blog/`
- `list.url_template`: 실제 작동 대상인 Crunchyroll News public API `/v1/en-US/stories/search?order_by=newest`
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
- `make_adapter` 손 실행: list 3건, 첫 글 body 263 chars.
- `register.py --config configs/host_funimation-com_blog_65f137c9.json` → baseline 20건 등록.
- `probe_smoke.py --stage 3 --stage 5` → PASS 1064, FAIL 0, WARN 0, SKIP 0.

## 일반화 안 함 이유

이 건은 Funimation의 특정 URL이 Crunchyroll News로 이전된 remap + Crunchyroll 전용 public API 조합이다. 같은 `posts_nonempty` failure는 누적 사례가 많지만, 이 케이스 하나만으로 generic probe나 recognizer를 넓히면 다른 Next.js shell 또는 root/category remap을 오인할 위험이 크다.
