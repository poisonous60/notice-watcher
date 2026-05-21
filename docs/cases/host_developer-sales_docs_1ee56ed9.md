---
slug: host_developer-sales_docs_1ee56ed9
url: https://developer.salesforce.com/docs/platform/release-notes/
status: ✅ 등록 (Salesforce developer docs release-note pages via official docs sitemap)
outcome: handcrafted
date: 2026-05-21
fix_layer: F
failure_keys: [capability_blocked, baseline_blocked, cloudflare_protected_site, salesforce_docs_sitemap]
config_strategy: handwritten
adapters_changed: [adapters/salesforce_docs.py, adapters/__init__.py]
engine_files_touched: []
tags: [manual-config, handwritten-adapter, salesforce, sitemap, curl-cffi, anti-bot]
requested_by: unknown
---

## 트리거

`https://developer.salesforce.com/docs/platform/release-notes/` 자동 등록 실패.

`last_feedback`: `[BLOCKED] verdict=cloudflare_protected_site — 정적·headless 진입 차단 (능력 부족, 정책 아님). stealth/storage_state 어댑터 재도전 대상.`

로컬 fresh probe 결과 `output/poll_state/host_developer-sales_docs_1ee56ed9.FAILED.json` 과 `output/probe/host_developer-sales_docs_1ee56ed9/` 를 생성했다.

## 진단

preflight: `miss — host_developer-sales_docs_1ee56ed9`.

- `configs/host_developer-sales_docs_1ee56ed9.json` 없음.
- `engine.recognizers.recognize("https://developer.salesforce.com/docs/platform/release-notes/")` 결과 `None`.
- fresh `register.py` 재현도 rc=5 capability_blocked.

`diagnosis.json` verdict: `CLOUDFLARE_PROTECTED_SITE`.

관찰:

- baseline 루트와 probe static GET 은 403 `BLOCKED_BOT`.
- Playwright S4는 사용자 URL에서 Salesforce 404 페이지를 받았고, 글 링크 후보가 없다.
- `curl_cffi` Chrome impersonation으로 `https://developer.salesforce.com/docs/ssg-sitemap.xml` 및 하위 sitemap은 200으로 접근 가능했다.
- 하위 sitemap에서 `release-notes`, `whatsnew`, `whatswasnew` URL 48개를 확인했다.

robots/polite_sleep: `robots.txt` 는 접근 가능했고 sitemap 경로를 명시한다. config/adapter는 5-8초 polite sleep을 둔다.

## 픽스

손어댑터 `SalesforceDocsReleaseNotesAdapter` 를 추가하고 handwritten config를 작성했다.

- 목록: official docs SSG sitemap index -> guide별 leaf sitemap -> release-note URL 필터.
- fetch: `curl_cffi.requests.get(..., impersonate="chrome")`.
- post_id: docs URL path 기반 안정 키.
- title: URL path에서 제품명 + Release Notes/What Was New를 생성.
- article: 개별 docs page를 fetch하여 `h1`/`main`/meta description을 본문과 요약으로 사용.

입력 URL 자체는 현재 404이므로, 동일 사이트의 공개 sitemap을 board source로 삼았다.

## 트랙 B 후보

- **2a (인식기 PATTERNS 확장)**: X — Salesforce developer docs release-note 집계 전용이며 범용 플랫폼 recognizer로 확대할 근거가 약하다.
- **2b (--article-url)**: X — 첫 글 오인이 아니라 입력 path 404 및 sitemap 경유 회수.
- **2c (probe heuristic)**: X — `capability_blocked` 누적은 많지만 이번 해결은 Salesforce docs의 official sitemap + curl_cffi 전용 adapter다. generic probe digest 신호를 추가해도 입력 URL 404는 풀리지 않는다.
- **2d (probe artifact 수정)**: X — 산출물 자체는 차단/404를 정확히 보고했다.

## 회귀 검증

영향 범위는 새 adapter export, `curl_cffi` dependency, 이 slug config다. 기존 config schema/engine/probe/prompt는 변경하지 않았다.

검증:

- `python scripts/register.py --config configs/host_developer-sales_docs_1ee56ed9.json` → baseline 30건 등록.
- `python scripts/probe_smoke.py --stage 3 --stage 5` → PASS 961 / FAIL 0.
- `python scripts/probe.py` 로 기본 REPS fixture 4개를 재생성한 뒤 `python scripts/probe_smoke.py` 전체 실행 → stage 1 통과, stage 2에서 `mabinogi` click fixture만 FAIL 1 (`article_sample.clicked_resolved_url=None`). 재시도해도 현재 사이트 overlay가 click probe를 가로채는 기존 fixture/timing 문제로 남았다.
