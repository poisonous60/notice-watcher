---
slug: host_velog-io_teo_0a627fc6
url: https://velog.io/@teo
status: ✅ 수동 config 등록 (Velog RSS, baseline 20건)
outcome: handcrafted
date: 2026-05-21
fix_layer: F
failure_keys: [register_subprocess_timeout, posts_nonempty]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [hand-config, rss, velog, spa, batch-2026-05-21-blogcms-gen4]
vocab_candidates:
  - candidate: feed_source_discovery
    confidence: med
    evidence:
      - "probe: feed_candidates.json had no Velog feed candidate"
      - "manual_check: https://v2.velog.io/rss/@teo returned RSS while https://velog.io/rss/@teo returned 404"
    reasoning: "Velog profile pages are React SPA shells but public RSS is available on v2.velog.io/api.velog.io; automatic feed-source discovery could avoid manual config."
    analysis_date: 2026-05-21
    deferred: true
---

## 진단

- last_feedback: 이전 batch 에서는 `register.py 실행 시간 초과(300s)` BUG 로 기록됐고, timeout fix 뒤에는 bounded rc=1 clean fail 로 수렴하는 대상이다. 로컬에는 `.FAILED.json` 이 없어 `triage.py show` 에 last_feedback 원문은 없었다.
- diagnosis verdict: `정적 HTTP로 충분`
- 매칭 분류: `docs/config 자동생성 실패 케이스.md` §2a. 정적 HTML 후보는 스켈레톤뿐이고 `first_article_url` 이 없어 자동 config 가 목록을 못 잡는 SPA/RSS 대체 경로 케이스다.
- 분기: 2e 수동 config. Playwright 금지 조건 때문에 RSS를 `httpx_html` XML 파서로 수집했다.
- preflight: miss — `configs/host_velog-io_teo_0a627fc6.json` 없음, recognizer 없음, 로컬 `.FAILED.json` 없음.
- 누적 cross-check: `register_subprocess_timeout` count=0, `posts_nonempty` count=43, `posts_nonempty.track_b_trigger=true`; deferred 후보도 다수 trigger 상태지만 이번 작업 allow-list 가 config/case 로 제한되어 Track B 코드는 보류했다.

## 해결

`configs/host_velog-io_teo_0a627fc6.json` 을 추가했다.

- 목록: `https://v2.velog.io/rss/@teo`
- strategy: `httpx_html`
- row: `channel > item`
- body: Velog article page의 정적 `body` HTML

주의: 사용자 메모의 `https://velog.io/rss/@teo` 는 이 dev box 에서 404였다. 같은 내용이 `https://v2.velog.io/rss/@teo` 와 `https://api.velog.io/rss/@teo` 에서 200 RSS 로 확인됐다.

## 회귀 검증

- `python scripts/register.py --config configs/host_velog-io_teo_0a627fc6.json` → PASS, baseline 20건.
- 첫 글 body selector: `body` 로 100자 이상 확보.
- 영향 사이트: 새 config 파일만 추가했다. 기존 engine/recognizer 변경 없음.

## Track B

Velog RSS discovery 는 일반화 가치가 있다. 다만 이번 hard-stop 이 config-only 라 `engine/recognizers/velog.py` 나 feed candidate heuristic 은 추가하지 않았다. RSS-via-`httpx_html` (`channel > item`) 자체는 기존 Medium config 와 같은 닫힌 어휘로 해결됐다.
