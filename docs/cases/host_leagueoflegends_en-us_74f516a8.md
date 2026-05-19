---
slug: host_leagueoflegends_en-us_74f516a8
url: https://www.leagueoflegends.com/en-us/news/
status: ✅ 손-config (httpx_json + script_root __NEXT_DATA__, 30건 baseline)
outcome: improved
date: 2026-05-19
fix_layer: E
failure_keys: [gen_fail_unknown, spa_no_external_api, next-data-inline-json]
config_strategy: httpx_json
adapters_changed: []
engine_files_touched: [engine/strategies/httpx_json.py, engine/config_schema.py]
tags: [riot, league-of-legends, next-data, ssr-inline-json, script-root, engine-extension]
requested_by: poisonous60
---

## 무엇이 일어났나

catalog batch 2026-05-19 에서 gen_fail (subkind 분류 미스). probe 가 정적 HTML 1.18MB 받지만 article 카드가 Next.js hydration 으로 렌더. HAR XHR 캡처에서 외부 article API 호출 X — 모든 데이터가 `<script id="__NEXT_DATA__">` inline JSON 안.

## 발견

`<script id="__NEXT_DATA__" type="application/json">` body 의 JSON path:

```
props.pageProps.page.blades[2].items
```

`blades[2].type == "articleCardGrid"`. 200 items, 각각 `{title, publishedAt, action: {payload: {url}}, description, category, media}`.

## 픽스 (engine 확장 — fix_layer E)

이 패턴 (Next.js/Nuxt/Sapper SSR + inline JSON island) 은 SPA 손-config 공통 영역. 손-adapter 박는 대신 engine 확장:

`engine/strategies/httpx_json` + `engine/config_schema`:

```python
list:
  script_root:
    selector: "script#__NEXT_DATA__"
  list_path: [props, pageProps, page, blades, 2, items]
  fields:
    post_id: {from: json, path: [action, payload, url], transform: [[regex_extract, "/([^/]+)/?$"]]}
    ...
```

`fetch_list` 가 `script_root` 발견 시 응답을 HTML 로 파싱하고 selector 의 `<script>` body 를 JSON parse 해서 payload 로 사용. 일반 JSON API config 와 같은 list_path/fields 호환.

## 함정

- `blades[2]` 인덱스 fragile. 사이트가 blade 순서 바꾸면 wrong section. 안정성 위해 `blades` 안 `type=="articleCardGrid"` 필터링이 이상 — engine 의 `type_field/type_allow` 옵션은 *each entry 안* 의 type field 검사라 entry 단위 list 안 적용 X. 인덱스 안정성에 의존.
- post_id 가 외부 URL 의 last segment (`lolesports.com/.../msi-2026-...`) 라 slug-shape. validation 의 STABLE_ID_RE cap 통과.
- 다른 Riot 도메인 뉴스 페이지 (KR/JP/EU) 도 같은 패턴 — 추후 catalog 추가 시 board 만 바꿔 재사용.

상세: `infra_catalog_batch_rev4_2026-05-19.md`.
