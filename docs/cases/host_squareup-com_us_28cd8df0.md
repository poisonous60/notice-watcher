---
slug: host_squareup-com_us_28cd8df0
url: https://squareup.com/us/en/press
status: ✅ 수동 config 등록 (static press cards, baseline 30건)
outcome: handcrafted
date: 2026-05-21
fix_layer: none
failure_keys: [posts_nonempty]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [hand-config, squareup, press, static-html]
---

## 진단

- 사용자 제공 실패: rc=1 gen_fail, selector fail로 `posts_nonempty` 계열 실패.
- 로컬 재현: 기존 `output/` snapshot이 없어 새 probe를 실행했다. LLM 단계는 `GEMINI_API_KEYS=0` 때문에 config 생성 전에 실패했지만, probe artifact는 생성됐다.
- diagnosis verdict: `정적 HTTP로 충분`.
- 매칭 분류: `docs/config 자동생성 실패 케이스.md` §2a. 목록 HTML은 정상이고, 자동 config가 row selector를 못 맞춘 경우다.
- preflight: miss — 기존 config/recognizer 없음, 로컬 실패 artifact 없음.
- 누적 cross-check: `posts_nonempty` 누적 49건, `track_b_trigger=true`. 이번 케이스는 probe의 1순위 `html_repeating_patterns`가 이미 실제 press card 53건을 가리켜 새 probe 신호 추가가 아니라 단일 config 작성이 맞다.

## 해결

`configs/host_squareup-com_us_28cd8df0.json`을 추가했다.

- 목록: `https://squareup.com/us/en/press`
- strategy: `httpx_html`
- row: `div.press-newsroom.latest-press-releases > div.press-release-preview`
- title/url/date: 카드 내부 press link, `h3`, `.font-eyebrow-small.color-gray`
- body: article page의 `main div.content`, fallback `main`

## 회귀 검증

- `python scripts/register.py --config configs/host_squareup-com_us_28cd8df0.json` → PASS, baseline 30건.
- 첫 글: `the-hat`, `2026-05-19T00:00:00+00:00`, title/body 추출 정상.
- 영향 사이트: 새 config 파일만 추가했다. 기존 engine/recognizer/probe 변경 없음.
- robots/polite_sleep: `robots.txt`는 `/us/en/press`를 disallow하지 않고 Crawl-Delay도 없다. 엔진 기본 host 간 sleep 정책을 사용한다.

## Track B

일반화 보류. `posts_nonempty` 누적은 많지만 이 케이스는 probe가 이미 정확한 list row 후보를 최상위로 추출했다. 새 schema/probe/prompt 변경 없이 단일 Square press config가 최소 해결이다.
