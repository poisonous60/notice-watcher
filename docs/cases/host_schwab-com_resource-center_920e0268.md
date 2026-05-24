---
slug: host_schwab-com_resource-center_920e0268
url: https://www.schwab.com/resource-center/insights
status: 🧩 수동 config — Schwab insights 정적 HTML row 로 목록 10건, 본문 추출 확인
outcome: handcrafted
date: 2026-05-24
failure_keys: [schema_invalid_css_selector]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [schwab, static-html, css-selector]
requested_by: batch
---

## 무엇이 일어났나

`/resource-center/insights` 는 정적 HTTP로 충분하고 실제 글 목록도 HTML 안에 있다. 자동 생성 config 는
목록 selector 에 `data-dl-component.title` 속성명을 그대로 넣었다.

`last_feedback`:

- `list.row_selector: CSS 선택자 컴파일 실패 — Malformed attribute selector ... 선택자='div[data-component="Mosaic"][data-dl-component.title="The latest commentary"] div[data-component="ArticleTile"]'`

`diagnosis.json`:

- `verdict: 정적 HTTP로 충분`
- `recommended_strategy: httpx (S1.H2)`
- `list_candidates: HTML 15건, JSON API 0건, hydration 0건`
- `first_article_url: https://www.schwab.com/learn/story/ready-or-not-digital-stock-market-is-coming`

## 픽스

`configs/host_schwab-com_resource-center_920e0268.json` 을 `httpx_html` config 로 작성했다.

- 목록: `https://www.schwab.com/resource-center/insights`
- row: `div[data-component="ArticleTile"]`
- 내부 글만 유지: `row_required_selector: a[href^="/learn/story/"]`
- `post_id`: row 의 `data-dl-link.id`, 없으면 `/learn/story/<slug>`
- `title`: row 의 `data-dl-link.name`
- `url`: `/learn/story/` href
- 본문: 글 페이지의 `div.w-full.max-w-story div[data-component="LockupBody"]`

자동 config 의 나머지 필드 추출은 probe 결과와 맞아 그대로 유지했고, invalid selector 만 더 단순한 row selector 로
줄였다.

## 회귀 검증

- recognizer preflight
  - `recognize('https://www.schwab.com/resource-center/insights')` -> `None`
- preflight 영향 변경 검사
  - FAILED 이후 `prompts/ engine/ probe/ generate/ engine/recognizers/` commit 0건
  - 같은 path uncommitted 변경 0건
- schema validation
  - `OK`
- `make_adapter` smoke
  - `fetch_list()` 10건
  - 첫 3개: `rising-yields-highlight-muni-opportunities`, `warsh-settles-as-yields-hit-historic-high`, `stock-market-update-open`
  - 첫 글 body length: `123465`
- `register.py --config`
  - 실행하지 않음. 이번 Codex 위임 범위에서 poll_state/triage marker 쓰기 작업은 피하고, Claude exit 단계에 맡긴다.

## 트랙 B 검토

- **2a (플랫폼 config) — X.** Schwab 전용 resource center HTML 구조이고 같은 플랫폼으로 일반화할 근거가 없다.
- **2b (`--article-url`) — X.** 첫 글 URL 은 실제 글 URL 이며, 실패 원인은 첫 글 오인이 아니다.
- **2c/2d (probe/prompt/engine) — X.** probe 는 `ArticleTile` row 후보와 first article 을 이미 잡았다. 실패는 자동 생성 config 의 단일 CSS selector 문법 오류다.
- **2e (수동 config) — O.** 단일 사이트 config selector 보정으로 해결된다.

일반화 안 되는 이유: 이 case 는 `data-dl-component.title` 처럼 점이 포함된 속성명을 LLM 이 CSS selector 에
잘못 쓴 단발 schema 실패다. validator 가 이미 정확한 피드백을 주고 있으므로 새 engine/probe 휴리스틱을 추가하지 않는다.

## 자가 점검 (§6)

1. **자리**: none/config only. 새 adapter/engine/probe/prompt/schema 변경 없음.
2. **이전 케이스**: 사용자가 `cases_index.py`/INDEX/DB 작업 금지를 명시해 query/backfill 은 실행하지 않았다.
3. **누구 깰까**: 새 config 파일 1개만 추가하므로 기존 config 영향 0.
4. **검증**: schema OK, make_adapter 목록 10건/본문 123465자.
5. **outcome=handcrafted**: 단일 수동 config 작성이며 generic 추론 개선이 아니다.
6. **fixture**: 새 strategy/heuristic 이 아니라 기존 `httpx_html` 사용이라 별도 fixture 추가 없음.
7. **트랙 B 사유**: 위 §트랙 B 검토 참조.
