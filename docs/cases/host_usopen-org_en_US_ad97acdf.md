---
slug: host_usopen-org_en_US_ad97acdf
url: https://www.usopen.org/en_US/news/index.html
status: ✅ 수동 config 등록 (relatedcontent JSON API)
outcome: handcrafted
date: 2026-05-25
requested_by: sports-batch
failure_keys: [err_http2_protocol_error, render_navigation_failed]
fix_layer: none
config_strategy: httpx_json
adapters_changed: []
engine_files_touched: []
tags: [usopen, sports, hand-config, httpx-json]
---

## 무엇이 일어났나

preflight: miss — 로컬 FAILED/probe artifact 없음. `triage.py show` 는 probe 산출물 부재를 보고했다.

US Open news app 도 Masters 와 같이 Chromium `Page.goto` 에서 `net::ERR_HTTP2_PROTOCOL_ERROR` 가 났다.
RSS 추정 후보는 유효 feed 가 아니었다. 앱 설정 `config_web.json` 의 `relatedContent.home` 계열이
`relatedcontent/rest/v2/uso_v1/...` public JSON news endpoint 를 가리키므로 그 경로를 사용했다.

## 픽스

`configs/host_usopen-org_en_US_ad97acdf.json` 을 추가했다.

- `strategy`: `httpx_json`
- `list.url_template`: `https://www.usopen.org/relatedcontent/rest/v2/uso_v1/en/content/byType/news?zone=2`
- `post_id`: `contentId`
- `title/url/date/author/category/summary/cover_image`: JSON item fields
- `article.content`: item detail endpoint 의 `description`

## 검증

- schema validation: `OK`
- inline adapter smoke: list 5건, 첫 article body 196자
- `register.py --config`: PASS, baseline 25건

## 트랙 B 검토

- 2a 인식기: 보류 — Masters 와 유사하지만 tenant/config path discovery 는 공통 recognizer 설계가 필요하다.
- 2b article URL 교정: X — browser navigation 이 HTTP/2 오류로 실패한다.
- 2c/2d probe/prompt: allow-list 밖이라 변경하지 않았다.
- 2e 수동 config: 적용.

일반화 안 되는 이유: `uso_v1` tenant, `zone=2`, endpoint config 가 host-specific 하다.

Root-cause/tradeoff: render entrypoint 는 Chromium HTTP/2 오류다. API config 는 같은 public news card stream 을
수집하지만 full article body 대신 description 을 본문으로 사용한다.
