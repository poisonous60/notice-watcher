---
slug: host_nseindia-com_resources_b0248e5e
url: https://www.nseindia.com/resources/exchange-communication-press-releases
status: "수동 config - NSE press-release JSON API 사용"
outcome: handcrafted
date: 2026-05-24
failure_keys: [fetch_list, posts_nonempty, wrong_first_article]
fix_layer: none
config_strategy: httpx_json
adapters_changed: []
engine_files_touched: []
tags: [nseindia, press-release, json-api, hand-config]
requested_by: batch
---

## 무엇이 일어났나

자동 생성은 `playwright_html` 로 `#PRContainer` / `#table-PressRelease` 를 기다리는 config 를 만들었지만,
검증에서 Playwright `Page.goto` 가 `net::ERR_HTTP2_PROTOCOL_ERROR` 로 실패했다. `httpx_html` 재시도는
정적 HTML 의 빈 컨테이너만 보고 `posts_nonempty: 0건` 으로 실패했다.

진단 인용:

- `last_feedback`: `[FAIL] fetch_list: 실행 실패: Error: Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://www.nseindia.com/resources/exchange-communication-press-releases`
- `diagnosis.json verdict`: `정적 HTTP로 충분`
- 실패 케이스: `docs/config 자동생성 실패 케이스.md` §2a (`fetch_list` / `posts_nonempty` 목록 추출 실패)
- 분기: 2e 수동 config. 페이지 JS가 쓰는 공개 JSON API가 있고, 손어댑터는 필요 없다.
- 누적 cross-check: `fetch_list` 6건, `posts_nonempty` 96건, `wrong_first_article` 4건 모두 `track_b_trigger=true`. 이번 건은 단일 NSE API 선택 문제라 공유 recognizer/engine 변경은 하지 않았다.
- preflight: `miss - host_nseindia-com_resources_b0248e5e`

probe 의 `first_article_url` 은 `https://www.nseindia.com/nse-academy/nse-academy-overview` 로, 실제 press release가 아니라
상단 내비게이션 링크였다. 정적 HTML 의 `#PRContainer` / `#table-PressRelease` 는 비어 있고
`/dist/js/sections/resources/ex-comm-press-cms20.js` 가 `/api/press-release-cms20` 응답으로 목록을 채운다.

## 픽스

`configs/host_nseindia-com_resources_b0248e5e.json` 을 `httpx_json` config 로 작성했다.

- 목록: `https://www.nseindia.com/api/press-release-cms20`
- `post_id`: JSON item `id`
- `title/published_at/category/summary`: `content.title`, `content.field_date`, `content.field_type`, `content.body`
- `url`: `content.field_file_attachement.url`
- `article.body_empty_acceptable=true`: API list item 자체가 body summary를 제공하고, attachment URL은 PDF인 경우가 많아 개별 article body를 hard requirement로 두지 않는다.

## 트랙 B 검토

- **2a (인식기) - X.** NSE 단일 사이트 API config 이며 같은 플랫폼 게시판군으로 일반화할 근거가 부족하다.
- **2b (`--article-url`) - X.** probe 의 첫 글 오인은 있었지만 실제 해결은 목록 source를 JSON API로 바꾸는 것이다.
- **2c/2d (probe/prompt/engine) - 보류.** JS 파일에서 API endpoint를 추출하는 일반화 후보는 있지만, 이번 요청은 slug-local fix surface로 제한되었다.
- **2e (수동 config) - O.** 공개 JSON API로 posts_nonempty를 안정적으로 만족한다.

일반화 안 되는 이유: `/api/press-release-cms20` 는 NSE press-release 전용 endpoint 이고, 전역 probe/recognizer 변경 없이 단일 config로 해결된다.

## 회귀 검증

- 스키마 OK.
- `make_adapter` 손 실행: `fetch_list(page_size=10)` -> 10건.
  - 첫 3건: `76274` / `76273` / `76272`
- `python scripts/probe_smoke.py --stage 3 --stage 5`
  - stage 3: 215 / 215 OK
  - stage 5: 89 파일, 955 케이스, 0 FAIL
  - summary: PASS 1171, FAIL 0
- `register.py --config` 는 이번 Codex 지시의 HARD STOP 범위에 맞춰 실행하지 않았다. 이 명령은 `.FAILED.json` / `triage_queue` / `poll_state` 를 정리할 수 있다.

## 자가 점검

1. **자리**: config only. 새 adapter/engine/probe/prompt/schema 변경 없음.
2. **이전 케이스**: cross-check 는 `fetch_list`/`posts_nonempty`/`wrong_first_article` 모두 누적 trigger 상태였지만, 이번 변경은 NSE 전용 API config 로 한정했다.
3. **누구 깰까**: 새 config 파일 1개만 추가하므로 기존 config 영향 0.
4. **검증**: schema, make_adapter, register, probe_smoke 로 확인한다.
5. **outcome=handcrafted**: 단일 사이트 config 작성이며 generic 추론 개선이 아니다.
6. **fixture**: 새 strategy/heuristic 이 아니라 기존 `httpx_json` 사용이라 별도 fixture 추가 없음.
