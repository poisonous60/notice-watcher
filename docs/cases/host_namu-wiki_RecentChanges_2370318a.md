---
slug: host_namu-wiki_RecentChanges_2370318a
url: https://namu.wiki/RecentChanges
status: ✅ 수동 config (playwright_html + a[href^=/w/] row, 30건 baseline)
outcome: improved
date: 2026-05-19
fix_layer: F
failure_keys: [gen_fail_unknown, spa_obfuscated_classes, vue-ssr-3kb-shell]
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [namuwiki, recent-changes, vue, obfuscated-classes, playwright-html, body-empty-acceptable]
requested_by: poisonous60
---

## 무엇이 일어났나

catalog batch run 2026-05-19 에서 gen_fail (subkind 분류 미스). namu.wiki HTML 직접 fetch 시 3608 bytes SSR shell — content 0. Vue 클라이언트 렌더로 RecentChanges 표 생성.

Playwright headless 로 렌더 후 220KB DOM. 하지만 클래스명이 의도적으로 obfuscated build-hash 형태 (`DpfUxXyh`, `qXQSihpq`, `g1g9baIZ` 등) — `tr`/`tbody`/`table[role=row]` 표준 selector 모두 매칭 X.

## 픽스

stable selector 만: `a[href^='/w/']` — wiki page link 187개 안정 (의도적 obfuscation 도 link 자체는 함수). 각 anchor = 한 row 의 wiki page 링크. URL-encoded UTF-8 path (`/w/%EC%82%AC%EC%9A%A9%EC%9E%90:LAVINA`).

handwritten config:
- strategy=`playwright_html` (SSR shell 만으로 부족)
- wait_selector=`a[href^='/w/']` (renderer 가 link 박은 후 row 잡음)
- row_selector=`a[href^='/w/']`
- post_id = `remove_prefix /w/` + `strip_query_fragment` (URL-encoded segment)
- title = `:self` text (anchor 내부)
- url = `urljoin https://namu.wiki` + `strip_query_fragment`
- published_at 추출 X — RecentChanges 의 timestamp 가 obfuscated 별도 column. body_empty_acceptable=true.

## 한계

- published_at 없어 polling 시 ordering 가능성 — slug 기반 dedupe 만으로 충분 (post_id = URL-encoded page name, immutable).
- 본문 추출 X (`article`/`main` selector 도 obfuscated). body_empty_acceptable=true 라 알림은 title + URL 만 발송.
- 의도적 obfuscation 사이트 = 크롤링 적대적. namu rebuild 시 anchor href 패턴 변하면 깨질 위험 (하지만 `/w/<page>` 는 wiki URL convention 이라 매우 안정적).

상세: `infra_catalog_batch_rev4_2026-05-19.md`.
