---
slug: host_adobe-com_products_2fe98bba
url: https://www.adobe.com/products/new-creative-cloud-features.html
status: ✅ 등록 (Adobe Creative Cloud features AEM fragments)
outcome: handcrafted
date: 2026-05-21
fix_layer: adapter
failure_keys: [capability_blocked, baseline_blocked, adobe_akamai, curl_cffi_impersonate, aem_fragments]
config_strategy: handwritten
adapters_changed: [adapters/adobe_creative_cloud.py]
engine_files_touched: []
tags: [manual-config, handwritten-adapter, anti-bot, adobe, creative-cloud]
requested_by: poisonous60
---

## 트리거

사용자 제공 증상:

`rc=5 capability_blocked`: `https://www.adobe.com/api/entries?sortBy=newest&perPage=10` 가 `ReadTimeout`.
자동 경로의 `playwright_html` 도 anti-bot/Cloudflare/Akamai 계층에서 막힌 것으로 보고됐다.

로컬 worktree에는 기존 `output/poll_state/host_adobe-com_products_2fe98bba.FAILED.json` 및
`output/probe/host_adobe-com_products_2fe98bba/` 가 없어 기존 `last_feedback` 원문은 확인하지 못했다.

## 진단

preflight: `miss — host_adobe-com_products_2fe98bba`.

- `configs/host_adobe-com_products_2fe98bba.json` 없음.
- `engine.recognizers.recognize("https://www.adobe.com/products/new-creative-cloud-features.html")` 결과 `None`.
- fresh `scripts/probe.py --lite` verdict: `BASELINE_BLOCKED`.
- probe 결과: httpx baseline/root/robots `ReadTimeout`, Playwright `net::ERR_HTTP2_PROTOCOL_ERROR`, HTML/JSON/hydration 후보 0건.
- `curl_cffi.requests.get(..., impersonate="chrome")` 는 현재 공개 페이지
  `https://www.adobe.com/creativecloud/features.html` 과 AEM fragment
  `https://main--cc--adobecom.aem.live/cc-shared/fragments/creativecloud/features/...` 를 읽을 수 있었다.
- 원래 URL `https://www.adobe.com/products/new-creative-cloud-features.html` 은 현재 dev box에서 Adobe 404를 반환한다.
  같은 내용의 현재 공개 페이지는 `https://www.adobe.com/creativecloud/features.html`.

## 픽스

`AdobeCreativeCloudFeaturesAdapter` 손어댑터와 handwritten config를 추가했다.

- `curl_cffi` Chrome impersonation 사용.
- current Adobe Creative Cloud features 페이지를 sanity fetch.
- AEM feature card index fragment에서 제품별 card fragment를 찾음.
- 각 card fragment에서 `post_id`/`title`/`category`/modal URL 추출.
- `fetch_article` 은 modal fragment의 `main` HTML을 본문으로 반환.
- config 파일명은 실패 slug 그대로 유지하고, `_source_url` 은 사용자가 요청한 원래 URL로 둠.

## 트랙 B 후보

- **2a (인식기 PATTERNS 확장)**: X — Adobe Creative Cloud features 단일 페이지 전용. 같은 플랫폼 게시판 패턴으로 일반화하기 어렵다.
- **2b (--article-url)**: X — 첫 글 오인이 아니라 목록 진입 자체가 차단되고 기존 API가 timeout.
- **2c (probe heuristic)**: X — probe artifact 안에 쓸 수 있는 목록/API 신호가 없었다. 해결 신호는 live AEM fragment 구조와 curl_cffi TLS impersonation이다.
- **2d (probe 수정)**: X — 기본 Playwright stealth도 `ERR_HTTP2_PROTOCOL_ERROR` 로 실패. site-specific adapter가 더 작고 안전하다.

## 검증

- `python -c "import json; from engine.config_schema import validate_config; ..."` PASS.
- `make_adapter` smoke PASS: 목록 6건.
- 첫 글 `fetch_article` PASS: 본문 2450자.
- `python scripts/register.py --config configs/host_adobe-com_products_2fe98bba.json` PASS:
  baseline 6건, state `output/poll_state/host_adobe-com_products_2fe98bba.json`.

## 한계

- 원래 `/products/new-creative-cloud-features.html` URL 은 현재 Adobe 404다. 등록은 같은 Creative Cloud features 목적의
  현재 공개 URL과 AEM fragments를 기준으로 한다.
- Adobe fragment에는 명시 날짜가 없어 `published_at` 은 비운다.
