---
slug: _bug_register_300s_timeout
url: multiple
status: ✅ 개선 — register subprocess 300s kill 전에 probe/preflight timeout 을 rc=1 clean fail 로 수렴
outcome: improved
date: 2026-05-21
fix_layer: F
failure_keys: [subprocess_timeout, probe_timeout, playwright_sync_greenlet, headless_teardown_hang]
config_strategy: none
adapters_changed: []
engine_files_touched: [scripts/register.py, probe/fetch_headless.py]
tags: [bugfix, register, probe, playwright, timeout, greenlet, batch-2026-05-21-blogcms]
---

## 무엇이 일어났나

`blogcms` batch 의 4개 URL 이 봇 worker 에서 `register.py 실행 시간 초과` 로 `.BUG.json`
경로를 탔다. 봇의 `bot/site_ops.py:blocking_register` 는 register subprocess 를 process group 으로
띄우고 timeout 시 kill 하므로 worker 무한 block 자체는 막고 있었다. 문제는 register.py 안쪽 phase 가
자기 budget 을 모르고 오래 버틴다는 점이었다.

대상:
- `https://brunch.co.kr/@springboot`
- `https://shopify.engineering/`
- `https://www.techradar.com/`
- `https://velog.io/@teo`

## root-cause

1. **probe phase 가 register 부모 timeout 에만 의존**했다.
   `scripts/register.py:_run_probe` 는 `subprocess.call(probe.py ...)` 만 쓰고 자체 timeout 이 없었다.
   `techradar` 산출물은 `list.html`, `article.html`, `list_candidates.json` 까지는 있는데
   `diagnosis.json`/`summary.txt` 가 없어 probe 후반부 또는 teardown 에서 중단된 정황이다.

2. **Playwright sync API 객체를 다른 thread 에서 닫았다.**
   `probe/fetch_headless.py:_bounded_close` 가 `context.close()` / `browser.close()` 를 별도 thread 에서
   호출했다. Playwright sync API 는 greenlet 이 생성 thread 에 묶이므로 teardown callback 이
   `greenlet.error: cannot switch to a different thread` 를 낼 수 있다. 이 오류는 register 의 실제
   실패 원인을 흐리고, teardown hang 과 결합하면 부모 subprocess timeout 까지 간다.

## 무엇을 바꿨나

### 1. `scripts/register.py` — bounded child process helper

`_run_child_bounded()` 를 추가했다. 자식 stdout/stderr 를 캡처하고 timeout 초과 시 process tree 를
죽인다. Windows 에서는 `taskkill /T /F /PID`, POSIX 에서는 새 session + kill 로 처리한다.

### 2. `scripts/register.py` — probe timeout

`_run_probe()` 가 `probe.py` 를 무한 대기하지 않고 `REGISTER_PROBE_TIMEOUT_S` 기본 120초 안에서만
기다린다. 초과 시 register 는 rc=-2 BUG 가 아니라 rc=1 `.FAILED.json` 으로 종료한다.

실패 기록은 `last_feedback="[FAIL] probe_timeout: ..."` 이라 hand-config/bug triage 에서 원인이
보인다.

### 3. `scripts/register.py` — article re-probe process isolation

preflight 의 글페이지 render+HAR re-probe 는 hidden child mode 로 분리했다.
부모 register 는 기본 45초(`REGISTER_ARTICLE_REPROBE_TIMEOUT_S`)만 기다리고, 초과하면
`article_candidates.json=[]` 로 계속 진행한다. Playwright teardown 이 멈춰도 register 본체와
LLM 생성 phase 를 잡아먹지 않는다.

### 4. `probe/fetch_headless.py` — greenlet thread 오류 제거

Playwright sync 객체 close 를 별도 thread 에서 호출하지 않는다. close 는 생성 thread 에서 수행하고,
hang bound 는 상위 bounded subprocess 가 담당한다. 이로써 `cannot switch to a different thread`
계열 오류를 제거했다.

## blast radius

- 봇의 `bot/site_ops.py` timeout/kill 구조는 유지했다. 바깥 안전망은 그대로고, register 내부에 더 이른
  clean-fail 안전망을 추가한 것이다.
- config schema, adapter, recognizer, selector 로직은 건드리지 않았다.
- `probe/extract.py:detect_mastodon_platform` 은 수정하지 않았다.

## 검증

- `python -m py_compile scripts/register.py probe/fetch_headless.py` PASS
- `python scripts/probe_smoke.py --stage 3 --stage 5` PASS, exit 0
- `python scripts/vocab_lint.py` PASS
- `REGISTER_PROBE_TIMEOUT_S=5 python scripts/register.py --wall-timeout 120 "https://www.techradar.com/"`
  → 약 8초 안에 rc=1, `host_techradar-com_root_8baaf5b7.FAILED.json` 생성. 300초 subprocess kill 없음.
- `python scripts/register.py --reuse-probe --gate-only "https://brunch.co.kr/@springboot"`
  → 약 3초, rc=6. 모든 게이트 통과, preflight/LLM skip.
- `python scripts/register.py --reuse-probe --gate-only "https://shopify.engineering/"`
  → 약 3초, rc=6. 모든 게이트 통과, preflight/LLM skip.
- `python scripts/register.py --reuse-probe --gate-only "https://velog.io/@teo"`
  → 약 3초, rc=3. board_shape 거부.

## SPA 개별 처리 상태

이번 변경은 SPA 별 config 를 완성하는 작업이 아니라 `register.py` timeout/greenlet 결함을 먼저 막는
generic robustness fix 다. `brunch` 와 `shopify` 는 기존 artifact 기준으로 게이트를 통과해 수동 config
또는 생성 품질 개선이 별도 과제로 남는다. `velog` 는 기존 artifact 기준 board_shape 로 거부된다.
`techradar` 는 probe 산출물 생성이 끝까지 완료되지 않는 케이스였고, 이제 clean fail 로 남는다.
