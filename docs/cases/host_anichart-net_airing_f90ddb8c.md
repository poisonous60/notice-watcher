---
slug: host_anichart-net_airing_f90ddb8c
url: https://anichart.net/airing
status: 🧩 손어댑터 — AniChart airing schedule GraphQL endpoint 로 baseline 30건 등록
outcome: handcrafted
date: 2026-05-21
requested_by: batch
failure_keys: [posts_nonempty, spa_shell_static_empty, graphql_post_api_schema_gap]
fix_layer: F
config_strategy: handwritten
adapters_changed: [adapters/anilist.py]
engine_files_touched: []
tags: [anichart, anilist, graphql, spa, airing]
vocab_candidates:
  - candidate: graphql_post_list
    confidence: med
    evidence:
      - output/probe/host_anichart-net_airing_f90ddb8c/traffic.article_click.har: POST https://graphql.anilist.co/
      - engine/strategies/httpx_json.py: httpx_json only issues GET requests
      - docs/cases/host_anilist-co_search_784ba699.md: same GraphQL POST schema gap
    reasoning: "목록 데이터는 공개 GraphQL POST API에 있었지만 현재 선언형 httpx_json schema는 POST body/query를 표현하지 못한다."
    analysis_date: 2026-05-21
    deferred: true
---

## 진단 인용

- `last_feedback`: `[FAIL] posts_nonempty: 0건`
- `diagnosis.json verdict`: `정적 HTTP로 충분`
- 매칭 분류: `docs/config 자동생성 실패 케이스.md` §2a (`posts_nonempty: 0건`) + SPA shell/JS 데이터 로딩. 정적 HTML 반복 후보는 `head > link`, `head > meta`뿐이었고, 실제 목록은 렌더 후 GraphQL POST 응답에 있었다.
- 분기: 2e. `httpx_json`은 GraphQL POST body를 표현하지 못해 config만으로는 API 호출을 만들 수 없었다.
- 누적 cross-check: `posts_nonempty` 74건으로 track_b trigger=true. 다만 이번 root-cause는 이미 `host_anilist-co_search_784ba699`에서 `graphql_post_list` vocab 후보로 남긴 schema gap과 동일하다.
- preflight: `b-hit — host_anichart-net_airing_f90ddb8c [5665fa8]`. 실패 이후 probe/engine 영향 영역 커밋이 있어 `register.py --reuse-probe`를 재시도했고, 자동 config는 통과했지만 링크 전체 selector로 `settings` 같은 내비게이션을 baseline에 포함했다.

## 무엇이 일어났나

`https://anichart.net/airing` 은 Vue shell이다. 정적 HTML에는 `<div id="app"></div>`만 있고, probe의 반복 패턴도 head metadata만 잡았다. Playwright 렌더 후에는 `https://graphql.anilist.co/` POST 응답에 `Page.airingSchedules[]` 데이터가 내려왔다.

자동 생성기는 `playwright_html` selector를 세 번 시도했지만 `[FAIL] posts_nonempty: 0건`으로 실패했다. preflight b-hit 재시도에서는 `a[href^='/']` 전체를 row로 잡아 검증은 통과했지만, seasonal nav/settings 링크까지 post로 등록하는 품질 문제가 있었다.

## 무엇을 바꿨나

기존 `adapters/anilist.py`의 GraphQL 호출 패턴을 재사용해 `AniListAiringAdapter`를 추가했다.

- GraphQL query: `Page.airingSchedules(sort: TIME, notYetAired: true)`
- `post_id`: airing schedule id
- `title`: media title + episode number
- `url`: AniList media `siteUrl`
- `published_at`: `airingAt` Unix timestamp UTC ISO8601
- `content_html`: media description + summary + AniList link

`configs/host_anichart-net_airing_f90ddb8c.json` 은 `strategy: handwritten`, `adapter: AniListAiringAdapter`만 참조한다.

## 회귀 검증

- 스키마 OK.
- `make_adapter` 손 실행: list 10건, 첫 글 `407364`, body 590 chars.
- `python scripts/register.py --config configs/host_anichart-net_airing_f90ddb8c.json` → baseline 30건.
- `python scripts/probe_smoke.py --stage 3 --stage 5` → PASS (stage 3: 176/176 OK, stage 5: 80 files, 872 cases, 0 FAIL).

## 트랙 B

- **2a (recognizer) — 보류.** `anichart.net/airing` 단일 slug 처리이며, recognizer를 추가하면 slug schema가 바뀔 수 있어 이번 작업 범위를 넘는다.
- **2b (`--article-url`) — X.** 정적 HTML에 article URL이 없고 목록 데이터는 GraphQL schedule 응답이다.
- **2c/2d (probe 개선) — X.** probe는 `traffic.article_click.har`에서 GraphQL POST 응답을 이미 보존했다. 실패는 추출 누락보다 선언형 `httpx_json`이 POST GraphQL을 표현하지 못하는 엔진 어휘 한계다.

일반화 안 되는 이유: GraphQL POST를 선언형 config로 풀려면 `httpx_json` schema/strategy/prompt/fixture를 함께 확장해야 한다. 이번 slug는 기존 AniList 계열 adapter 표면을 좁게 확장하고, `graphql_post_list` vocab 후보에 누적한다.

## 자가 점검 (§6)

1. **자리**: F (handwritten adapter + config).
2. **이전 케이스**: `host_anilist-co_search_784ba699` 와 같은 GraphQL POST schema gap.
3. **누구 깰까**: 새 adapter class는 이번 config에서만 참조하므로 기존 config 영향 0.
4. **검증**: register baseline 30건 OK, adapter list/body OK, probe_smoke stage 3/5 PASS.
5. **outcome=handcrafted**: dedicated adapter가 공개 GraphQL API를 직접 호출하는 수동 config라 generic 추론 개선이 아니다.
6. **fixture**: 새 strategy가 아니라 새 adapter라 stage 3 make_adapter 검증으로 충분.
7. **트랙 B 사유**: GraphQL POST schema 확장은 별도 vocabulary/engine 작업으로 분리.
