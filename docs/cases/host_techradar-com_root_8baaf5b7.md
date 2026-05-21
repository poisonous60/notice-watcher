---
slug: host_techradar-com_root_8baaf5b7
url: https://www.techradar.com/
status: ✅ 수동 config 등록 (static WDN list cards, baseline 30건)
outcome: handcrafted
date: 2026-05-21
fix_layer: F
failure_keys: [register_subprocess_timeout, posts_nonempty]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [hand-config, static-html, techradar, large-html, batch-2026-05-21-blogcms-gen4]
---

## 진단

- last_feedback: 이전 batch 에서는 `register.py 실행 시간 초과(300s)` BUG 로 기록됐다. 로컬에는 `.FAILED.json` 과 `output/probe/host_techradar-com_root_8baaf5b7/` 가 없어 `triage.py show` 에 last_feedback/diagnosis 원문은 없었다.
- diagnosis verdict: artifact 없음. 직접 `httpx` 확인 결과 `https://www.techradar.com/` 는 200 HTML 을 반환했다.
- 매칭 분류: `docs/config 자동생성 실패 케이스.md` §2a. 큰 HTML/JS 페이지지만 homepage 안에 정적 list card가 있고, 자동 probe hang 이 별도 timeout bug 로 분리된 케이스다.
- 분기: 2e 수동 config. 403/anti-bot 이 재현되면 capability_blocked 로 기록해야 하지만, 이번 dev box 확인에서는 차단이 없어서 `httpx_html` config 를 작성했다.
- preflight: miss — `configs/host_techradar-com_root_8baaf5b7.json` 없음, recognizer 없음, 로컬 `.FAILED.json`/probe artifact 없음.
- 누적 cross-check: `register_subprocess_timeout` count=0, `posts_nonempty` count=43, `posts_nonempty.track_b_trigger=true`; deferred 후보도 다수 trigger 상태지만 이번 작업 allow-list 가 config/case 로 제한되어 Track B 코드는 보류했다.

## 해결

`configs/host_techradar-com_root_8baaf5b7.json` 을 추가했다.

- 목록: `https://www.techradar.com/`
- strategy: `httpx_html`
- row: `li.wdn-listv2-item` 중 `a.wdn-listv2-item-link` 가 있는 cards
- body: `div#article-body`

## 회귀 검증

- `python scripts/register.py --config configs/host_techradar-com_root_8baaf5b7.json` → PASS, baseline 30건.
- 첫 글 body selector: `div#article-body` 로 100자 이상 확보.
- 영향 사이트: 새 config 파일만 추가했다. 기존 engine/recognizer 변경 없음.

## Track B

TechRadar probe artifact 가 없어 일반화 신호를 비교할 수 없었다. 이번 처리의 핵심은 Playwright 를 다시 쓰지 않고 큰 정적 HTML에서 list card와 article body를 직접 지정한 것이다. 향후 같은 Future/WDN 레이아웃이 반복되면 별도 recognizer 또는 row scoring 개선을 검토할 수 있다.
