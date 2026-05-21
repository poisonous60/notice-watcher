---
slug: host_wikicfp-com_cfp_4cc94e7b
url: https://www.wikicfp.com/cfp/
status: solved (HTTP allcfp config)
outcome: handcrafted
date: 2026-05-21
failure_keys: [https_timeout, static_html_available]
fix_layer: E
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [academic-batch, wikicfp, cfp, config]
requested_by: batch-2026-05-21-academic-track-a
---

## 결과

HTTPS는 이 환경에서 타임아웃됐지만, WikiCFP의 canonical HTTP 페이지는 정상 응답했다.
Root `/cfp/`에는 category/popular block이 섞여 있어 `/cfp/allcfp`를 polling source로 잡았다.

## 픽스

`configs/host_wikicfp-com_cfp_4cc94e7b.json`을 추가했다.

- strategy: `httpx_html`
- list URL: `http://www.wikicfp.com/cfp/allcfp`
- row selector: `a[href*='event.showcfp']`
- post_id: `eventid`
- article content: `div.contsec`

## 검증 메모

- httpx HTTP `/cfp/allcfp`: 200, CFP event links 20+건
- sample article page: 200, `div.contsec` 본문 확인
- `validate_config` + `make_adapter.fetch_list(page_size=100)`: 20건, duplicate post_id 0건
- 첫 article body: 8990자
