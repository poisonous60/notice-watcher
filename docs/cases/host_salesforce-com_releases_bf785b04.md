---
slug: host_salesforce-com_releases_bf785b04
url: https://www.salesforce.com/releases/
status: ✅ 등록 (Salesforce release resources card list)
outcome: handcrafted
date: 2026-05-21
fix_layer: none
failure_keys: [capability_blocked, fetch_list_403, salesforce_releases]
config_strategy: httpx_html
adapters_changed:
engine_files_touched: []
tags: [manual-config, static-html, release-resources, anti-bot]
requested_by: unknown
---

## 트리거

`https://www.salesforce.com/releases/` 자동 등록 실패. 사용자 제공 요약:

`rc=1 gen_fail: fetch_list 403 Forbidden (anti-bot)`.

로컬 worktree에는 `output/poll_state/host_salesforce-com_releases_bf785b04.FAILED.json` 및 `output/probe/host_salesforce-com_releases_bf785b04/`가 없어서 기존 `last_feedback`/`diagnosis.json` 원문은 확인하지 못했다.

## 진단

preflight: `miss — host_salesforce-com_releases_bf785b04`.

- `configs/host_salesforce-com_releases_bf785b04.json` 없음.
- `engine.recognizers.recognize("https://www.salesforce.com/releases/")` 결과 `None`.
- 로컬 `.FAILED.json`/probe artifact 없음.

fresh dev-box 관찰에서는 `https://www.salesforce.com/releases/`가 `https://www.salesforce.com/products/innovation/releases/`로 301 이동한 뒤 200을 반환했다. 응답 헤더에 Akamai 쿠키가 있고, 원 실패가 403이므로 N100 또는 자동 probe의 UA/header 조건에서 anti-bot으로 막혔을 가능성이 있다.

robots.txt 확인: `/products/innovation/releases/` 경로는 명시 `Disallow` 대상이 아니다.

## 픽스

수동 config 1개를 추가했다.

- `strategy: httpx_html`
- `url_template: https://www.salesforce.com/releases/`
- `row_selector: [data-module-type='card_resource']`
- `post_id`: `data-module-id`
- `title`: `data-module-name`
- `url`: 카드 내부 첫 링크
- `summary`/`category`: 카드 본문과 badge
- `article.body_empty_acceptable: true`

링크 대상은 Salesforce+, Trailhead, 외부 페이지가 섞일 수 있어 본문 fetch는 의도적으로 list-only로 둔다. 알림에는 카드 제목/링크/요약을 쓰고, 본문 미추출 경고는 기존 `body_empty_at_baseline` 흐름에 맡긴다.

## 트랙 B 후보

- **2a (인식기 PATTERNS 확장)**: X — Salesforce releases 단일 랜딩 페이지 전용. 플랫폼 패턴 아님.
- **2b (--article-url)**: X — 첫 글 오인이 아니라 목록 fetch 403 및 랜딩 카드 추출 문제.
- **2c (probe heuristic)**: X — `capability_blocked`/`fetch_list_403` 누적은 많지만 이번은 generic anti-bot 우회가 아니라 공개 정적 HTML의 사이트 전용 카드 selector로 해결.
- **2d (probe artifact 수정)**: X — 기존 artifact 부재.

## 회귀 검증

영향 범위는 새 config 파일 1개뿐이다. 공유 engine/probe/prompt/recognizer를 변경하지 않았으므로 기존 configs에 대한 구조적 영향은 없다.
