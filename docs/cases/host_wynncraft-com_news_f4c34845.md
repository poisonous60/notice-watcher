---
slug: host_wynncraft-com_news_f4c34845
url: https://wynncraft.com/news/
status: 🔧 손 config (httpx_json) — Wynncraft public publisher API
outcome: handcrafted
date: 2026-05-28
requested_by: batch
failure_keys: [posts_nonempty]
fix_layer: F
config_strategy: httpx_json
adapters_changed: []
engine_files_touched: [engine/config_schema.py, engine/strategies/httpx_json.py]
tags: [wynncraft, nuxt-spa, public-api, httpx-json, dict-values]
---

## 무엇이 일어났나

`[FAIL] posts_nonempty: 0건`; list path wrong.

catalog URL `https://wynncraft.com/news/`는 Nuxt SPA shell이고 정적 HTML에는 row가 없다. live HTML/JS가 public API `https://api.wynncraft.com/v3/publisher/articles/list/article`를 사용한다. API는 CORS-open JSON을 반환하지만 `results`가 배열이 아니라 rank key dict다.

`?page=1`과 기본 URL은 같은 page 1을 반환하고, `?page=2`도 동작한다. detail API는 `https://api.wynncraft.com/v3/publisher/articles/fetch/article/{pk}`가 200 JSON을 반환한다. public article page는 `/news/blog/{pk}`가 200이다.

preflight: miss — 이미 등록된 config/recognizer 없음. 이 작업은 사용자가 `2026-05-28 games-online-live-service-04` gen_fail 잔여 2건을 Track A 손 config로 즉시 처리하라고 slug와 catalog URL을 명시했다.

screen-out: none — live API에 게시글 10건과 pagination metadata가 있어 content-as-list, soft-404, fake feed가 아니다.

## 무엇을 바꿨나 (fix layer: F — httpx_json dict values opt-in)

`configs/host_wynncraft-com_news_f4c34845.json` — `httpx_json`.

- `list.url_template`: `https://api.wynncraft.com/v3/publisher/articles/list/article`
- `pagination`: query param `page`
- `list_path`: `["results"]`
- `list_values: true`: rank-keyed dict의 values를 rows로 사용
- `post_id`: `pk`
- `title`: `title`
- `category`: `type`
- `url`: `https://wynncraft.com/news/{category}/{post_id}`
- `published_at`: `published_at`
- `summary`: `recap`
- `article.url_template`: `https://api.wynncraft.com/v3/publisher/articles/fetch/article/{post_id}`
- `article.content`: first text block `content[0].content`, fallback `recap`

`engine/strategies/httpx_json.py`는 `list_values: true`일 때만 `list_path` 결과 dict를 `values()` 배열로 변환하도록 opt-in 보완했다. `engine/config_schema.py`에는 해당 boolean을 선언했다.

## Track B 6-layer audit

- E schema: miss — config schema validation으로 잡을 수 있는 오류가 아니라 JSON shape 표현력 문제.
- D retry feedback: miss — retry feedback이 있어도 `results` dict를 rows로 바꾸는 어휘가 없으면 생성 config가 계속 0건.
- C probe digest: miss — API URL과 payload는 확인 가능하지만 strategy가 dict rows를 배열로 소비하지 못함.
- B few-shot: miss — 예제 추가만으로 현재 strategy의 배열 전제를 우회할 수 없음.
- A system prompt: miss — prompt가 `list_path: ["results"]`를 쓰게 해도 engine이 list가 아니라고 버림.
- F engine: hit — `httpx_json` strategy에 opt-in `list_values`를 추가해야 rank-keyed result object를 표현 가능.

## 회귀 검증

- live curl 확인: API 기본 URL/page=1/page=2 모두 200, `results` type dict, page=1 sample pk/title/published_at 확인.
- live URL 확인: `https://wynncraft.com/news/blog/116` status 200.
- 손 실행: list 3건 샘플에서 title/date/url 정상, first article API body 650 chars.
- unit: `python -m pytest tests/engine/test_httpx_json_list_values.py` → 1 passed.
- `python scripts/register.py "https://wynncraft.com/news/" --config configs/host_wynncraft-com_news_f4c34845.json` → rc=0, baseline 10건.

## 일반화 범위

Wynncraft config 자체는 사이트 전용 수동 config다. 다만 `results`가 dict인 public JSON API는 현재 `httpx_json`의 닫힌 표현으로 등록할 수 없어, broad auto-conversion 대신 `list_values: true` opt-in으로만 열었다.
