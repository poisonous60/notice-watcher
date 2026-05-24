---
slug: host_fitchratings-co_research_f256080a
url: https://www.fitchratings.com/research
status: 🔧 손어댑터 config (GraphQL POST, baseline 확인)
outcome: handcrafted
date: 2026-05-24
requested_by: batch
failure_keys: [posts_nonempty, matches_probe_first_article]
fix_layer: F
config_strategy: handwritten
adapters_changed: [adapters/fitch_ratings.py]
engine_files_touched: []
tags: [fitch-ratings, graphql-post, handwritten]
---

## 무엇이 일어났나
`[FAIL] posts_nonempty: 0건`.

probe 는 `https://www.fitchratings.com/research` 정적 HTML에서 실제 연구 목록을 찾지 못했고, nav 링크인 `https://www.fitchratings.com/events` 를 `first_article_url` 로 잡았다. 자동 생성은 `httpx_html`/`playwright_html` selector 를 바꿔가며 3회 시도했지만 모두 목록 0건으로 실패했다.

## 무엇을 바꿨나 (fix layer: F — 손어댑터)
**`adapters/fitch_ratings.py`** — Fitch 사이트 JS chunk의 `researchSection`이 호출하는 공개 GraphQL `getInsights` POST를 그대로 사용한다.

- 목록: `POST https://api.fitchratings.com/`
- query: `getInsights.rows { publishedDate docType reportType slug title marketing { contentAccessType language } }`
- URL: `https://www.fitchratings.com/research/{slug}`
- 본문: API가 목록 메타만 주므로 제목/분류/날짜/원문 링크를 content_html로 보강한다.

**`configs/host_fitchratings-co_research_f256080a.json`** — `strategy: handwritten`, `adapter: FitchRatingsResearchAdapter`.

## 회귀 검증
- 스키마 OK.
- `make_adapter` 손 실행: list 비어 있지 않음, 첫 글 3건 출력, article body chars 확인.
- `python scripts/probe_smoke.py --stage 3 --stage 5` 실행.

## 일반화 검토
Track B 후보는 `httpx_json`에 POST body/GraphQL query vocab을 추가하는 것이다. 다만 이는 공용 strategy와 config schema 변경이며 Fitch 단건 해결보다 영향 범위가 크다. 이번 요청은 slug 단위 최소 fix라 전역 엔진 확장은 보류했다.
