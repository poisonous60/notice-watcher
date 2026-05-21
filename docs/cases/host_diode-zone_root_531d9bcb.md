---
slug: host_diode-zone_root_531d9bcb
url: https://diode.zone/
status: ✅ 자동 등록 가능 (PeerTube recognizer + PeerTubeAdapter 신규 — API v1 직접 호출)
outcome: handcrafted
date: 2026-05-21
fix_layer: F
failure_keys: [posts_nonempty, article_body_len]
config_strategy: handwritten
adapters_changed: [PeerTubeAdapter]
engine_files_touched: [engine/recognizers/peertube.py, adapters/peertube.py, adapters/__init__.py, probe/extract.py, scripts/probe.py, scripts/register.py]
tags: [peertube, fediverse, platform-recognizer, json-api, batch-2026-05-21-fedi]
---

## 무엇이 일어났나

`diode.zone/` 은 PeerTube app-shell 이라 일반 HTML 목록 추출로는 최신 영상 row 를 안정적으로 얻기 어렵다. 정적 HTML 에는 PeerTube 고유 marker 가 있다.

- `<meta property="og:platform" content="PeerTube">`
- `window.PeerTubeServerConfig`
- 공개 API: `GET <base>/api/v1/videos?sort=-publishedAt&count=N`

## 무엇을 바꿨나

### 1. `adapters/peertube.py` — `PeerTubeAdapter` 신규

- `fetch_list`: `/api/v1/videos?sort=-publishedAt&count=<page_size>` 호출.
- `post_id`: `uuid` 우선, fallback 으로 `shortUUID`/`id`.
- `title`: `name`, `published_at`: `publishedAt`, 본문: `description`.
- `fetch_article`: `/api/v1/videos/{uuid}` 로 상세 description 을 가져온다.

### 2. `engine/recognizers/peertube.py`

- URL-only recognizer 는 PeerTube 고유 API path(`/api/v1/videos`)만 잡는다.
- root URL 과 generic `/videos` 는 false-positive 위험이 있어 probe marker dispatch 로만 처리한다.

### 3. `probe/extract.py` + `scripts/probe.py` + `scripts/register.py`

- `detect_peertube_platform`: `og:platform=PeerTube`, `window.PeerTubeServerConfig`, `/api/v1/config` marker 를 추출한다.
- `write_list_candidates` 에 `peertube_platform` 키 추가.
- `register.py` 가 `peertube_platform.is_peertube` 를 보면 LLM 호출 전 `PeerTubeAdapter` config 등록을 시도한다.

## 검증

- API 직접 검증: `https://diode.zone/api/v1/videos?sort=-publishedAt&count=5` → 5건.
- Adapter smoke:
  - 5건 수집.
  - 첫 3건 post_id/title/published:
    - `082b498e-9309-439d-b210-cf2bf5753264` — `ShinyHunters Instructure Canvas Hack Onion Site Screencast` — `2026-05-07T20:58:44.285Z`
    - `16a72be4-9cb1-45ea-8e75-f1c4a3e96b39` — `Betrayal in Halo 3 MCC` — `2026-04-18T02:24:18.569Z`
    - `6cd45dec-1670-485d-a8a9-21d5c972591a` — `2026-02-14 - AMD DRM on X with high mouse poll rate freezes/stutters` — `2026-02-15T00:38:12.057Z`
  - 첫 글 본문 297자.

## 회귀 검증

- `tests/probe_heuristics/test_detect_peertube_platform.py` 추가.
- `tests/recognizers/test_peertube.py` 추가.
- generic `/videos` 는 URL-only recognizer 미매칭으로 둬서 비-PeerTube 사이트 false-positive 를 피한다.

## outcome = handcrafted

fix_layer F. PeerTube 공통 API 를 손어댑터와 플랫폼 marker dispatch 로 처리하는 known-platform 확장이다.

## 트랙 B 검토

- (2a) 플랫폼 인식기/adapter — 적용. PeerTube API v1 이 안정 표면.
- (2b) `--article-url` 재시도 — 적용 X. 실패 원인이 첫 글 URL 하나가 아니라 SPA/app-shell 구조.
- (2c) probe 휴리스틱 — 적용. generic 추론 개선이 아니라 known-platform dispatch marker.
- (2d) probe 오작동 — 적용 X. API adapter 로 우회하는 편이 단순하다.
