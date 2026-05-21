---
slug: host_shopify-enginee_root_25b7d4e3
url: https://shopify.engineering/
status: ✅ 수동 config 등록 (static article cards, baseline 16건)
outcome: handcrafted
date: 2026-05-21
fix_layer: F
failure_keys: [register_subprocess_timeout, posts_nonempty]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [hand-config, static-html, shopify-engineering, js-heavy, batch-2026-05-21-blogcms-gen4]
---

## 진단

- last_feedback: 이전 batch 에서는 `register.py 실행 시간 초과(300s)` BUG 로 기록됐고, timeout fix 뒤에는 bounded rc=1 clean fail 로 수렴하는 대상이다. 로컬에는 `.FAILED.json` 이 없어 `triage.py show` 에 last_feedback 원문은 없었다.
- diagnosis verdict: `정적 HTTP로 충분`
- 매칭 분류: `docs/config 자동생성 실패 케이스.md` §2a. probe 상위 후보가 nav/resources 링크와 섞였고 첫 후보도 topic URL 이라 자동 config 가 글 row를 못 고른 케이스다.
- 분기: 2e 수동 config. homepage HTML 안에 실제 `article.article--index` 카드와 article page의 `articleBody` 가 정적으로 있어 `httpx_html` 로 충분했다.
- preflight: miss — `configs/host_shopify-enginee_root_25b7d4e3.json` 없음, recognizer 없음, 로컬 `.FAILED.json` 없음.
- 누적 cross-check: `register_subprocess_timeout` count=0, `posts_nonempty` count=43, `posts_nonempty.track_b_trigger=true`; deferred 후보도 다수 trigger 상태지만 이번 작업 allow-list 가 config/case 로 제한되어 Track B 코드는 보류했다.

## 해결

`configs/host_shopify-enginee_root_25b7d4e3.json` 을 추가했다.

- 목록: `https://shopify.engineering/`
- strategy: `httpx_html`
- row: internal article cards only, excluding `/topics/` and `/authors/` links
- body: `div[itemprop='articleBody']`

## 회귀 검증

- `python scripts/register.py --config configs/host_shopify-enginee_root_25b7d4e3.json` → PASS, baseline 16건.
- 첫 글 body selector: `div[itemprop='articleBody']` 로 100자 이상 확보.
- 영향 사이트: 새 config 파일만 추가했다. 기존 engine/recognizer 변경 없음.

## Track B

일반화 후보는 static article card 후보를 nav/resources 후보보다 승격하는 probe scoring 이다. 하지만 이번 변경 범위는 config-only 이고, 사이트별 HTML 구조가 특수해 code heuristic 은 보류했다.
