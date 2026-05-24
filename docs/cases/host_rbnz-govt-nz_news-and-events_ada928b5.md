---
slug: host_rbnz-govt-nz_news-and-events_ada928b5
url: https://www.rbnz.govt.nz/news-and-events/news
status: 🧩 수동 config — RBNZ Coveo 목록을 Playwright로 수집
outcome: handcrafted
date: 2026-05-24
failure_keys: [fetch_list_403, article_body_len]
fix_layer: none
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [rbnz, coveo, central-bank, single-site]
requested_by: batch
---

## 무엇이 일어났나

`https://www.rbnz.govt.nz/news-and-events/news` 는 RBNZ 뉴스 목록이다. probe 산출물의
`list.html` 에는 `div.coveo-result-list-container > div.CoveoResult` 뉴스 행이 10개 렌더되어 있고,
첫 글은 `/news-and-events/news/2026/05/financial-system-resilient-amid-heightened-global-risks` 였다.

자동 생성은 올바른 Coveo row selector 근처까지 갔지만 마지막 시도에서 `pagination.kind=query_param` 으로
`?page=1` 을 붙였고, 그 URL이 403을 반환했다. 현재 live plain httpx 에서는 canonical URL도 403이라
브라우저 경로가 필요하다. 이전 playwright 시도는 article selector 가
`div#article-content .component.rich-text... > div.component-content > section...` 처럼 너무 구체적이라
실제 첫 rich-text 본문을 못 잡아 `article_body_len` 0자로 실패했다.

## 픽스

`configs/host_rbnz-govt-nz_news-and-events_ada928b5.json` 생성. 목록은 canonical URL만 쓰도록
`pagination.kind=none` 으로 고정하고, `playwright_html` 이 probe가 본 Coveo 결과 컨테이너를 기다린다.
본문은 실제 article DOM 의 `#article-content .component.rich-text .component__body` 로 낮췄다. 다만 목록을
먼저 연 같은 Playwright 세션에서 article로 이동하면 사이트가 challenge shell을 줄 수 있어,
polling 자체가 깨지지 않도록 `body_empty_acceptable=true` 를 둔다.

## Track B 검토

- **2a 인식기 — X.** 한 기관의 고정 뉴스 페이지라 재발 source 가 없다.
- **2b article-url — X.** 목록의 article URL은 이미 절대 URL로 제공된다.
- **2c/2d probe/generate — X.** 실패는 이 사이트의 `?page=1` 403과 과구체 selector 조합이며, 같은 유형을 일반화할 근거가 부족하다.
- **2e 수동 config — O.** 단일 사이트 canonical list URL + 안정적인 DOM selector 로 충분하다.

일반화 안 되는 이유: Coveo를 쓰지만 공개 JSON/API 후보가 없고, 문제의 핵심은 이 host의 HTTP 403 및 page query 정책이다.

## 회귀 검증

- `preflight: miss — host_rbnz-govt-nz_news-and-events_ada928b5` (config/recognizer 없음, FAILED 이후 영향 영역 변경 없음)
- probe 신호: `list_candidates.json` 에 CoveoResult 10건, `article.html` 에 첫 rich-text 본문 존재.
- `register.py --config configs/host_rbnz-govt-nz_news-and-events_ada928b5.json` → baseline 9건 등록.
- `ConfigAdapter.fetch_list(page_size=5)` → 5건, first post `financial-system-resilient-amid-heightened-global-risks`.
- direct article-only `fetch_article()` → body length 3356. list-then-article same session은 challenge shell로 body 0자라 optional 처리.
- 영향 사이트: 0개. 새 단일 config만 추가했고 공유 코드/recognizer/prompt는 변경하지 않았다.
