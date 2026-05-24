---
slug: host_bankofcanada-ca_press_878c0d81
url: https://www.bankofcanada.ca/press/
status: 🧩 수동 config — Bank of Canada press 랜딩의 정적 HTML row 로 baseline 5건 등록
outcome: handcrafted
date: 2026-05-24
failure_keys: [llm_json_parse, wordpress_rest_401]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [bankofcanada, wordpress, static-html, press]
requested_by: batch
---

## 무엇이 일어났나

`/press/` 는 정적 HTML 로 충분히 접근 가능하고 실제 press row 도 서버 응답 안에 있다. 하지만 자동 생성은
Gemini 응답 JSON 파싱 실패로 3회 실패했다.

`last_feedback`:

- `gemini 호출/파싱 실패: 모델 응답을 JSON 으로 파싱 실패`

`diagnosis.json`:

- `verdict: 정적 HTTP로 충분`
- `recommended_strategy: httpx (S1.H2)`
- `list_candidates: HTML 13건, JSON API 0건, hydration 0건`

probe 는 WordPress REST marker 도 찾았지만, live 확인 결과 Bank of Canada REST API 는 인증 없이
접근할 수 없다.

```text
https://www.bankofcanada.ca/wp-json/wp/v2/posts?per_page=5&_embed
401 {"code":"rest_cannot_access","message":"DRA: Only authenticated users can access the REST API."}
```

따라서 기존 WordPress REST recognizer 로는 이 board 를 처리할 수 없다.

## 픽스

`configs/host_bankofcanada-ca_press_878c0d81.json` 을 `httpx_html` config 로 작성했다.

- 목록: `https://www.bankofcanada.ca/press/`
- row: `main article.media`
- 내부 글만 유지: `row_required_selector: h3.media-heading a[href^='https://www.bankofcanada.ca/']`
- `post_id`: row id `post-<id>`
- `title/url/published_at/summary`: `.media-heading`, `.media-date`, `.media-excerpt`
- 본문: 글 페이지의 `div.post-content`

외부 언론 링크가 섞이는 `selected media activities` 행은 본문 fetch 안정성을 위해 제외했다.

## 회귀 검증

- recognizer preflight
  - `recognize('https://www.bankofcanada.ca/press/')` -> `None`
- preflight 영향 변경 검사
  - FAILED 이후 `prompts/ engine/ probe/ generate/ engine/recognizers/` commit 0건
  - 같은 path uncommitted 변경 0건
- schema validation
  - `OK`
- `make_adapter` smoke
  - `fetch_list()` 5건
  - 첫 3개 body length: `253417=2239`, `253319=349`, `253189=33`
- `python scripts/register.py --config configs/host_bankofcanada-ca_press_878c0d81.json`
  - baseline 5건 등록

## 트랙 B 검토

- **2a (플랫폼 config) — X.** WordPress marker 는 있지만 REST API 가 401 이라 기존 WordPress REST
  recognizer 로 확장할 수 없다. Bank of Canada 전용 HTML 구조다.
- **2b (`--article-url`) — X.** 첫 글 URL 은 실제 글 URL 이고, 실패 원인은 첫 글 오인이 아니라 LLM JSON
  파싱 실패다.
- **2c/2d (probe/prompt/engine) — 보류.** `llm_json_parse`/`generation_parse_fail` 누적 query 는 0건이라
  같은 failure_key 의 track B trigger 가 없다. 모델 출력 파싱 안정화는 별도 Track B 작업으로 다룰 수 있다.
- **2e (수동 config) — O.** 단일 사이트의 정적 HTML row 와 본문 selector 로 해결된다.

일반화 안 되는 이유: 이 config 는 인증 차단된 WordPress REST 를 우회해 Bank of Canada 사이트의
press 랜딩 HTML 구조를 직접 읽는 단일 host 수동 config 이며, generic 추론이나 platform dispatch 를
개선하지 않는다.

## 자가 점검 (§6)

1. **자리**: none/config only. 새 adapter/engine/probe/prompt/schema 변경 없음.
2. **이전 케이스**: `llm_json_parse` 0건, `generation_parse_fail` 0건. 직접 track B trigger 없음.
3. **누구 깰까**: 새 config 파일 1개만 추가하므로 기존 config 영향 0.
4. **검증**: schema OK, make_adapter 5건, register baseline 5건.
5. **outcome=handcrafted**: 단일 수동 config 작성이며 generic 추론 개선이 아니다.
6. **fixture**: 새 strategy/heuristic 이 아니라 기존 `httpx_html` 사용이라 별도 fixture 추가 없음.
7. **트랙 B 사유**: 위 §트랙 B 검토 참조.
