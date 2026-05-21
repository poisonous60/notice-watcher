---
slug: host_anilist-co_search_784ba699
url: https://anilist.co/search/anime
status: 🧩 손어댑터 — AniList GraphQL endpoint 로 top anime baseline 30건 등록
outcome: handcrafted
date: 2026-05-21
failure_keys: [title_nonempty, matches_probe_first_article, graphql_post_api_schema_gap]
fix_layer: F
config_strategy: handwritten
adapters_changed: [adapters/anilist.py]
engine_files_touched: []
tags: [anilist, graphql, spa, search, anime]
vocab_candidates:
  - candidate: graphql_post_list
    confidence: med
    evidence:
      - output/probe/host_anilist-co_search_784ba699/list_candidates.json: traffic_json_api_candidates[0] method=POST url=https://anilist.co/graphql
      - engine/strategies/httpx_json.py: httpx_json only issues GET requests
    reasoning: "목록 데이터는 공개 GraphQL POST API에 있었지만 현재 선언형 httpx_json schema는 POST body/query를 표현하지 못한다."
    analysis_date: 2026-05-21
    deferred: true
---

## 무엇이 일어났나

`https://anilist.co/search/anime` 는 Vue 렌더 shell 이고, 목록 데이터는 `https://anilist.co/graphql` POST 요청으로 내려왔다. probe 는 JSON API 후보를 잡았지만 현재 `httpx_json` 전략은 GET JSON만 표현한다. 그래서 자동 생성은 `playwright_html` 로 렌더 DOM을 긁으려 했고, 실제 데이터가 채워지기 전의 loading card에서 `post_id`만 URL로 잡고 title은 비워 `[FAIL] title_nonempty` 로 실패했다.

`first_article_url` 은 footer의 `https://discord.gg/TF428cr` 로 잡혀 `matches_probe_first_article` 경고도 같이 났다. 이 URL은 게시글이 아니라 외부 커뮤니티 링크라 `--article-url` 교정 대상이 아니다.

## 픽스

손어댑터 `AniListMediaAdapter` 추가:
- `https://graphql.anilist.co` 에 공개 GraphQL POST 요청을 보낸다. `anilist.co/graphql` 는 직접 호출 시 403으로 `graphql` subdomain 사용을 요구한다.
- 현재 config는 `media_type=ANIME`, `sort=SCORE_DESC`, `board=search/anime` 으로 top anime 목록을 반환한다.
- `post_id=id`, `title=title.userPreferred`, `url=siteUrl`, `published_at=startDate`, `summary=status/format/score/popularity`, `content_html=description` 을 쓴다.

검증:
- `python scripts/register.py --config configs/host_anilist-co_search_784ba699.json` → baseline 30건 등록.
- `make_adapter` 스모크 → 목록 5건, 첫 본문 716자.
- `python scripts/probe_smoke.py --stage 3 --stage 5` → PASS.

## 트랙 B (일반화 후보)

- **2a (인식기) — 보류.** recognizer 를 추가하면 현재 URL slug 가 `host_anilist-co_search_784ba699` 에서 플랫폼 slug 로 바뀔 수 있어 이번 단건 cleanup 범위를 넘는다.
- **2b (`--article-url`) — X.** probe first article 이 Discord 외부 링크라 진짜 글 URL 교정으로 해결되는 구조가 아니다.
- **2c/2d (probe 개선) — 부분 후보.** probe 는 POST GraphQL 후보를 이미 잡았다. 실패는 probe 추출 누락보다 `httpx_json` schema 가 POST body/query를 표현하지 못하는 엔진 어휘 한계다.

일반화 안 되는 이유: GraphQL POST를 선언형 config로 표현하려면 `httpx_json` schema/strategy/prompt/fixture를 함께 확장해야 한다. 이번 slug 처리는 손어댑터로 좁히고, `graphql_post_list` vocab 후보로 남긴다.

## 자가 점검 (§6)

1. **자리**: F (새 handwritten adapter + config).
2. **이전 케이스**: `title_nonempty` 5건, `matches_probe_first_article` 6건으로 label trigger 는 켜져 있으나, 이번 root-cause 는 별도 `graphql_post_api_schema_gap`.
3. **누구 깰까**: 새 adapter는 `configs/host_anilist-co_search_784ba699.json` 에서만 참조되므로 기존 config 영향 0.
4. **검증**: register baseline 30건 OK, adapter list/body OK, probe_smoke stage 3/5 PASS.
5. **outcome=handcrafted**: dedicated adapter가 공개 GraphQL API를 직접 호출하는 수동 config라 generic 추론 개선이 아니다.
6. **fixture**: 새 strategy가 아니라 새 adapter라 stage 3 make_adapter 검증으로 충분.
7. **트랙 B 0건 사유**: GraphQL POST schema 확장은 별도 vocabulary/engine 작업으로 분리.
