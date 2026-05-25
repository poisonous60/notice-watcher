---
slug: host_laliga-com_en-GB_bb18edb0
url: https://www.laliga.com/en-GB/news
status: ✅ 수동 config 등록 (playwright_html render)
outcome: handcrafted
date: 2026-05-25
requested_by: sports-batch
failure_keys: [probe_timeout, render_timeout]
fix_layer: none
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [laliga, sports, hand-config, playwright-html]
---

## 무엇이 일어났나

preflight: miss — 로컬에 `output/probe/host_laliga-com_en-GB_bb18edb0/` 와 FAILED.json 이 없었다.
`triage.py show` 는 probe 산출물이 없다고 보고했다. 원격 artifact pull 은 이 세션에서 SSH helper가
timeout 되어 사용하지 못했고, dev box live inspection 으로 재확인했다.

batch 실패는 `probe_timeout (120s)` 였다. LALIGA news page 는 Next.js 기반이지만 headless Chromium 에서
`div[data-event-action='UltimasNoticias']` row 가 정상 렌더된다. RSS 후보는 확인되지 않았고 `/en-GB/rss/news`,
`/en-GB/news/rss` 는 404였다.

## 픽스

`configs/host_laliga-com_en-GB_bb18edb0.json` 을 추가했다.

- `strategy`: `playwright_html`
- `list.url_template`: 원 URL `https://www.laliga.com/en-GB/news`
- `row_selector`: `div[data-event-action='UltimasNoticias']`
- `post_id/url`: `/en-GB/news/<slug>` href
- `title/category/date`: row 내부 텍스트와 `time`
- `article.content`: 상세 페이지 `article`
- `headless` 는 설정하지 않아 N100 기본값 `true` 를 사용한다.

## 검증

- schema validation: `OK`
- inline adapter smoke: list 5건, 첫 article body 2417자
- `register.py --config`: PASS, baseline 24건

## 트랙 B 검토

- 2a 인식기: X — LALIGA 단일 사이트 DOM 이고 반복 플랫폼 신호는 없다.
- 2b article URL 교정: X — 목록과 본문 URL 은 row href 로 충분하다.
- 2c/2d probe/prompt: 보류 — timeout 회피는 새 휴리스틱보다 수동 render config 가 더 작다.
- 2e 수동 config: 적용.

일반화 안 되는 이유: 사이트별 Next.js/Styled Components DOM 에 의존한다. 같은 LALIGA 계열 반복 전에는
recognizer 를 만들 근거가 부족하다.

Root-cause/tradeoff: probe 단계의 render timeout 이 원인이다. Playwright polling 은 안정적이지만 httpx보다
느려서 `polite_sleep` 5~6초와 30초 nav cap 을 둔다.
