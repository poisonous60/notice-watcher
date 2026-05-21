---
slug: host_lemmy-ml_root_9bc876aa
url: https://lemmy.ml/
status: ✅ 자동 등록 가능 (Lemmy recognizer + LemmyAdapter 신규 — API v3 직접 호출)
outcome: handcrafted
date: 2026-05-21
fix_layer: F
failure_keys: [posts_nonempty, article_body_len]
config_strategy: handwritten
adapters_changed: [LemmyAdapter]
engine_files_touched: [engine/recognizers/lemmy.py, adapters/lemmy.py, adapters/__init__.py, probe/extract.py, scripts/register.py]
tags: [lemmy, fediverse, platform-recognizer, json-api, batch-2026-05-21-fedi]
---

## 무엇이 일어났나

`2026-05-21-fedi` batch 의 Lemmy instances 가 일반 HTML pipeline 에서 실패했다.

- `lemmy.ml/`: SSR HTML/Anubis interstitial 사이에서 정적 후보가 `head > meta`뿐이라 `posts_nonempty: 0건`.
- `lemmy.dbzer0.com/`: federation feed 에서 `ap_id`를 post key처럼 쓰면 중복/불안정해질 수 있음.
- `midwest.social/`: link-only post 가 많아 본문 HTML 기준 검증이 `article_body_len` 으로 흔들림.
- `lemmy.world`, `lemmy.zip`, `programming.dev`, `feddit.*`, `aussie.zone`: web UI HTML 은 403/anti-bot 가능.

공통 해법은 HTML scraping 이 아니라 Lemmy API v3:
`GET <base>/api/v3/post/list?sort=New&limit=N&type_=Local`.

## 무엇을 바꿨나

### 1. `adapters/lemmy.py` — `LemmyAdapter` 신규

- `__init__(base_url, community_name=None, sort="New", type_="Local")`.
- `fetch_list`: `/api/v3/post/list` 호출. 기본 `type_=Local` 로 remote firehose 를 줄인다.
- `post_id`: `post.post.id` 를 문자열화. `ap_id` 는 federation origin 이라 polling key 로 쓰지 않음.
- `fetch_article`: `/api/v3/post?id=<id>` 호출. markdown body 는 안전하게 HTML paragraph 로 변환하고, link-only post 는 외부 URL 링크를 본문으로 합성한다.

### 2. `engine/recognizers/lemmy.py`

- 직접 recognizer 는 Lemmy 고유 API path(`/api/v3/post/list`)만 잡는다.
- root URL 과 `/c/<community>` 는 URL 만으론 false-positive 위험이 있어 직접 매칭하지 않는다.
- `build_config(base_url, community_name=None)` 는 probe marker dispatch 와 공유한다.

### 3. `probe/extract.py` + `scripts/register.py`

- `detect_lemmy_platform`: `window.isoData`/`site_res.local_site`/`join-lemmy`/Lemmy interstitial OG title marker 를 추출.
- `write_list_candidates` 에 `lemmy_platform` 키 추가.
- `register.py` 가 `lemmy_platform.is_lemmy` 를 보면 LLM 호출 전 `LemmyAdapter` config 등록을 시도한다.

## 검증

- `python scripts/probe.py "https://lemmy.ml/"` 재실행 후 `list_candidates.json` 에
  `lemmy_platform: {"is_lemmy": true, "base_url": "https://lemmy.ml"}` 확인.
- API 직접 검증:
  - `lemmy.ml`: 5건, post_id unique, title nonempty, 첫 본문 540자.
  - `lemmy.dbzer0.com`: 5건, post_id unique, title nonempty, 첫 본문 6187자.
  - `lemmy.world`: 5건, post_id unique, title nonempty, 첫 본문 105자.
  - `lemmy.zip`, `programming.dev`, `feddit.org`, `midwest.social`: 목록 3건 확인.
  - `aussie.zone`, `feddit.de`: `type_=Local` 기준 0건이면 known-platform 등록은 폴백한다.

## 회귀 검증

- 같은-host false-positive 방지: root URL 과 generic `/c/<community>` 는 URL-only recognizer 미매칭.
- probe marker test: Lemmy SSR `window.isoData` 와 Anubis OG title marker 양쪽 커버.
- 영향 사이트: 기존 configs 0개. 새 adapter export 는 `make_adapter` 경로만 추가한다.

## outcome = handcrafted

fix_layer F. 알려진 플랫폼 Lemmy 를 새 adapter/recognizer 로 처리하는 플랫폼 config 확장이다.
generic 추론이 미지 구조를 더 푸는 변화가 아니므로 `outcome: handcrafted`.

## 트랙 B 검토

- (2a) 플랫폼 인식기/adapter — 적용. Lemmy 공통 API v3 가 안정 표면.
- (2b) `--article-url` 재시도 — 적용 X. 실패 원인이 첫 글 URL 하나가 아니라 HTML UI 구조/차단.
- (2c) probe 휴리스틱 — 적용. 단 generic 추론 개선이 아니라 known-platform dispatch marker.
- (2d) probe 오작동 — 적용 X. API adapter 로 우회하는 편이 단순하고 안정적.
