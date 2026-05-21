---
slug: host_brunch-co-kr_springboot_58aa9ddd
url: https://brunch.co.kr/@springboot
status: ✅ 수동 config 등록 (Brunch RSS, baseline 20건)
outcome: handcrafted
date: 2026-05-21
fix_layer: F
failure_keys: [register_subprocess_timeout, posts_nonempty]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [hand-config, rss, brunch, spa, batch-2026-05-21-blogcms-gen4]
vocab_candidates:
  - candidate: feed_source_discovery
    confidence: high
    evidence:
      - "output/probe/host_brunch-co-kr_springboot_58aa9ddd/feed_candidates.json: head-alternate https://brunch.co.kr/rss/@@2MrI"
      - "manual_check: https://brunch.co.kr/rss/@@2MrI returned RSS with 20 items"
    reasoning: "Probe already found the alternate RSS link, but generation did not convert it into a channel > item httpx_html config."
    analysis_date: 2026-05-21
    deferred: true
---

## 진단

- last_feedback: 이전 batch 에서는 `register.py 실행 시간 초과(300s)` BUG 로 기록됐고, timeout fix 뒤에는 bounded rc=1 clean fail 로 수렴하는 대상이다. 로컬에는 `.FAILED.json` 이 없어 `triage.py show` 에 last_feedback 원문은 없었다.
- diagnosis verdict: `캡처 헤더 주입 시 정적 가능`
- 매칭 분류: `docs/config 자동생성 실패 케이스.md` §2a. profile HTML 에 글 목록 후보가 있지만 probe 의 첫 후보는 magazine 링크이고, 실제 안정 경로는 `<link rel=alternate>` RSS 다.
- 분기: 2e 수동 config. Playwright 없이 probe 가 찾은 RSS를 `httpx_html` XML 파서로 수집했다.
- preflight: miss — `configs/host_brunch-co-kr_springboot_58aa9ddd.json` 없음, recognizer 없음, 로컬 `.FAILED.json` 없음.
- 누적 cross-check: `register_subprocess_timeout` count=0, `posts_nonempty` count=43, `posts_nonempty.track_b_trigger=true`; deferred 후보도 다수 trigger 상태지만 이번 작업 allow-list 가 config/case 로 제한되어 Track B 코드는 보류했다.

## 해결

`configs/host_brunch-co-kr_springboot_58aa9ddd.json` 을 추가했다.

- 목록: `https://brunch.co.kr/rss/@@2MrI`
- strategy: `httpx_html`
- row: `channel > item`
- article URL: RSS link의 `@@2MrI/{id}` 를 사용자 URL 형태인 `@springboot/{id}` 로 정규화
- body: Brunch article page의 `.wrap_body`

사용자 메모의 `https://brunch.co.kr/rss/@@springboot` 는 200이지만 body 0 bytes 였다. probe artifact 의 `head-alternate` 가 가리킨 `@@2MrI` RSS가 실제 feed 다.

## 회귀 검증

- `python scripts/register.py --config configs/host_brunch-co-kr_springboot_58aa9ddd.json` → PASS, baseline 20건.
- 첫 글 body selector: `.wrap_body` 로 100자 이상 확보.
- 영향 사이트: 새 config 파일만 추가했다. 기존 engine/recognizer 변경 없음.

## Track B

`feed_candidates.json` 에 RSS가 있었는데 생성이 이를 쓰지 못한 케이스다. 일반화 후보는 feed source discovery 또는 RSS 후보를 config writer 에 더 강하게 주입하는 개선이다. 이번 hard-stop 에서는 코드 변경을 하지 않았다.
