---
slug: host_fedia-io_root_1f0bc0d6
url: https://fedia.io/
status: ⚠️ 플랫폼 감지 추가, fedia.io 현재 API 401로 등록 폴백
outcome: handcrafted
date: 2026-05-21
fix_layer: F
failure_keys: [posts_nonempty, capability_blocked]
config_strategy: httpx_json
adapters_changed: []
engine_files_touched: [engine/recognizers/mbin.py, probe/extract.py, scripts/probe.py, scripts/register.py]
tags: [mbin, kbin, fediverse, platform-recognizer, json-api, batch-2026-05-21-fedi]
---

## 무엇이 일어났나

`fedia.io/` 는 mbin/kbin 계열 threadiverse aggregator 다. 정적 HTML 은 로그인 화면으로 내려오지만 mbin marker 는 남아 있다.

- `<body data-controller="mbin notifications">`
- meta keywords: `mbin, content aggregator, open source, fediverse`
- nav: `/threads`, `/microblog`, `/magazines`

공식 API 표면은 `GET <base>/api/entries?sort=newest&perPage=N` 이지만, 2026-05-21 dev box 확인 기준 `fedia.io` 는 이 endpoint 와 `/api/magazines` 모두 401 을 반환했다.

## 무엇을 바꿨나

### 1. `engine/recognizers/mbin.py`

- `build_config(base_url)` 는 `httpx_json` config 를 만든다.
- 목록: `/api/entries?sort=newest&perPage={page_size}`.
- `list_path`: `items`.
- `post_id`: `entryId`, `title`: `title`, `published_at`: `createdAt`, `author`: `user.username`, `category`: `magazine.name`, 본문: `body`.
- API path(`/api/entries`) 와 magazine path(`/m/<magazine>`)만 URL-only recognizer 로 잡는다.

### 2. `probe/extract.py` + `scripts/probe.py` + `scripts/register.py`

- `detect_mbin_platform`: `data-controller=mbin/kbin`, mbin/kbin+fediverse meta, threads/microblog/magazines nav 를 추출한다.
- `write_list_candidates` 에 `mbin_platform` 키 추가.
- `register.py` 가 `mbin_platform.is_mbin` 를 보면 LLM 호출 전 mbin `httpx_json` config 등록을 시도한다.
- API 가 401/빈 목록이면 `_register_built_config` 가 실패로 보고 일반 파이프라인으로 폴백한다.

## 검증

- `https://fedia.io/` 정적 HTML 에서 mbin marker 확인.
- API 직접 검증:
  - `https://fedia.io/api/entries?sort=newest&perPage=5` → `401 Unauthorized`.
  - `https://fedia.io/api/magazines` → `401 Unauthorized`.
- Adapter smoke: mbin generated config 로 `fetch_list(page=1, page_size=5)` 실행 시 `HTTPStatusError 401 Unauthorized`.

## 회귀 검증

- `tests/probe_heuristics/test_detect_mbin_platform.py` 추가.
- `tests/recognizers/test_mbin.py` 추가.
- `/threads` 같은 generic path 는 URL-only recognizer 에서 제외했다. XenForo `/threads/...` false-positive 를 막기 위함이다.

## outcome = handcrafted

fix_layer F. mbin 공통 API schema 를 known-platform config 로 추가했다. `fedia.io` instance 는 현재 API 접근이 막혀 capability issue 로 남는다.

## 트랙 B 검토

- (2a) 플랫폼 인식기/config — 적용. mbin API schema 를 재사용한다.
- (2b) `--article-url` 재시도 — 적용 X. 실패 원인이 첫 글 URL 하나가 아니라 instance API 접근 제한.
- (2c) probe 휴리스틱 — 적용. generic 추론 개선이 아니라 known-platform dispatch marker.
- (2d) probe 오작동 — 적용 X. fedia.io 는 API 401 이 현재 blocker.
