---
slug: host_microsoft-com_en-us_000c6d5a
url: https://www.microsoft.com/en-us/microsoft-365/roadmap
status: 🔧 손 config (작동중, baseline 30, httpx_json)
outcome: handcrafted
date: 2026-05-21
failure_keys: [published_at_iso, article_body_len, nav_only_same_host]
config_strategy: httpx_json
adapters_changed: []
engine_files_touched: []
tags: [microsoft-365, roadmap, json-api, rss-linked-api]
---

## 무엇이 일어났나
사용자 제공 실패는 `gen_fail`: `fetch_article` 실패와 `published_at_iso` 파싱 실패였다. 자동 생성 config가 Microsoft 365 Roadmap의 월 단위 rollout date(`2027-06`)를 `2027-06T00:00:00+09:00`처럼 잘못 조합해 ISO8601 검증을 통과하지 못했다.

dev box 재현에서는 현재 코드의 nav-only gate가 먼저 동작해 `등록 거부 — 단일 article (nav-only same-host)`로 끝났다. 하지만 probe 산출물에는 실제 목록 API가 이미 잡혀 있었다.

- `diagnosis.json`: `verdict=정적 HTTP로 충분`
- `list_candidates.json`: `traffic_json_api_candidates[0].url=https://www.microsoft.com/releasecommunications/api/v2/m365?...`, `value` 배열 20건
- HTML 반복 후보는 제품/헤더/푸터/마케팅 블록 중심이라 Roadmap item 목록으로 쓰기 부적절

## 무엇을 바꿨나
`configs/host_microsoft-com_en-us_000c6d5a.json` 수동 config를 추가했다.

- strategy: `httpx_json`
- list: `https://www.microsoft.com/releasecommunications/api/v2/m365?$count=true&includeFacets=true&top=50&skip=0&$orderby=created%20desc`
- article: 같은 API에 `$filter=id eq {post_id}`를 걸어 상세 `description`을 본문으로 사용
- `published_at`: rollout month(`generalAvailabilityDate`)가 아니라 ISO 문자열인 `created` 사용
- `url`: `https://www.microsoft.com/en-us/microsoft-365/roadmap?id={post_id}`
- `polite_sleep`: robots.txt에 Crawl-Delay 없음. probe 권장 5초+에 맞춰 5~6초 지정

Roadmap 페이지 자체도 RSS 버튼으로 `https://www.microsoft.com/releasecommunications/api/v2/m365/rss`를 공개하고, 같은 `releasecommunications/api/v2/m365` API를 페이지에서 호출한다. 별도 우회나 차단 회피는 하지 않았다.

## 회귀 검증
- `python scripts/register.py --config configs/host_microsoft-com_en-us_000c6d5a.json` → PASS, baseline 30건
- 샘플: `560707 2026-05-20T23:15:13.6872125Z Microsoft Purview: Information Protection ...`
- `fetch_article`는 API 상세 응답의 `description`을 본문으로 채운다.

## 일반화 안 하는 이유
이 케이스는 Microsoft 365 Roadmap 전용 API 경로와 필드(`id`, `created`, `description`, `status`)에 의존한다. 같은 공개 API를 쓰는 다른 Microsoft Release Communications board가 추가로 들어오기 전까지 recognizer나 probe 휴리스틱으로 일반화하지 않는다.
