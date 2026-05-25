---
slug: host_masters-com_en_US_749a5209
url: https://www.masters.com/en_US/news/index.html
status: ✅ 수동 config 등록 (relatedcontent JSON API)
outcome: handcrafted
date: 2026-05-25
requested_by: sports-batch
failure_keys: [err_http2_protocol_error, render_navigation_failed]
fix_layer: none
config_strategy: httpx_json
adapters_changed: []
engine_files_touched: []
tags: [masters, sports, hand-config, httpx-json]
---

## 무엇이 일어났나

preflight: miss — 로컬 FAILED/probe artifact 없음. `triage.py show` 는 probe 산출물 부재를 보고했다.

Chromium `Page.goto("https://www.masters.com/en_US/news/index.html")` 는 dev box 에서도
`net::ERR_HTTP2_PROTOCOL_ERROR` 로 실패했다. RSS 추정 후보(`/en_US/rss/news.xml`,
`/en_US/news/index.rss`)는 404였다. 대신 앱 설정 `config_web.json` 이
`relatedContent.news` 와 `relatedcontent/rest/v2/masters_v1/...` 공개 JSON endpoint 를 참조한다.

## 픽스

`configs/host_masters-com_en_US_749a5209.json` 을 추가했다.

- `strategy`: `httpx_json`
- `list.url_template`: `https://www.masters.com/relatedcontent/rest/v2/masters_v1/en/content/byType/news`
- `post_id`: `contentId`
- `title/url/date/author/category/summary/cover_image`: JSON item fields
- `article.content`: item detail endpoint 의 `description`

## 검증

- schema validation: `OK`
- inline adapter smoke: list 5건, 첫 article body 202자
- `register.py --config`: PASS, baseline 25건

## 트랙 B 검토

- 2a 인식기: 보류 — Masters/US Open 이 같은 vendor API 형태를 공유하지만 host별 tenant id 가 다르다.
- 2b article URL 교정: X — browser navigation 자체가 HTTP/2 오류다.
- 2c/2d probe/prompt: allow-list 밖이라 변경하지 않았다.
- 2e 수동 config: 적용.

일반화 안 되는 이유: `masters_v1` tenant 와 app config 경로가 사이트 전용이다.

Root-cause/tradeoff: render entrypoint 는 Chromium HTTP/2 오류로 막힌다. API config 는 안정적으로 baseline 을
만들지만 article body 는 full article HTML 이 아니라 public card description 이다.
