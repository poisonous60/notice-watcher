---
slug: infra_headless_browser_profile_2026-05-22
url: https://www.livechart.me/news
status: ✅ probe generic 개선 — real Chrome 우선 + CF interstitial 대기 + fingerprint 통일로 anti-bot 오분류 줄이고 target 404/entry blocked 정확히 분류 (S4-first reorder 는 review 에서 revert)
outcome: improved
date: 2026-05-22
fix_layer: C
failure_keys: [capability_blocked, baseline_blocked, entry_blocked, target_not_found]
config_strategy: none
adapters_changed: []
engine_files_touched: [probe/fetch_headless.py, probe/fetch_headful.py, probe/diagnose.py, scripts/playwright_daemon.py]
tags: [anti-bot, headless, chrome, cloudflare, probe-engine, track-b]
---

## 무엇이 일어났나

7개 capability_blocked 계열 URL을 재probe했다. 목표는 per-site config가 아니라 *입력 URL 그대로* headless anti-bot 진입 능력을 generic하게 올리는 것.

초기 결과:

| URL | before verdict | 핵심 신호 |
|---|---|---|
| akiba-souken `/anime/` | `BASELINE_BLOCKED` | DNS `ERR_NAME_NOT_RESOLVED` |
| livechart `/news` | `분류 보류` | static은 404인데 headless가 Cloudflare challenge 403으로 밀림 |
| melonbooks detail | `BASELINE_BLOCKED` | TCP reset, age-gate 이전 연결 차단 |
| otaquest `/` | `BASELINE_BLOCKED` | httpx read timeout + Playwright timeout |
| sentai `/blogs/news` | `BASELINE_BLOCKED` | TLS/connect timeout 또는 reset |
| skeb `/` | `CLOUDFLARE_PROTECTED_SITE` | 루트/robots/target 모두 429 |
| ufotable `/news/` | `분류 보류` | 루트는 OK, target path만 403 |

## 원인

두 가지 gap이 섞여 있었다.

1. Playwright bundled Chromium + old-ish UA/viewport 조합이 일부 Cloudflare 경로에서 더 쉽게 challenge를 받았다.
2. (가설) `scripts/probe.py`의 S4 headless ↔ S1 static 병렬 두드림이 anti-bot 경로에서 headless 첫 진입을 challenge로 오염시킬 수 있다 — codex가 `PROBE_HEADLESS_FIRST=1` 기본 reorder를 넣었으나 **review에서 revert**했다 (전 사이트 probe 순서·속도 광범위 변경 + 미검증 + 7개 회복에 기여 0 → 정당화 안 됨, CLAUDE.md §8a over-broad 회피). 나머지 contained 개선만 유지.

## 변경

- `probe/fetch_headless.py`
  - `PROBE_BROWSER_CHANNEL` 기본값을 `chrome,msedge,bundled`로 두고, 설치된 real Chrome/Edge를 먼저 사용한다.
  - UA, screen, timezone, `Accept-Language`, `navigator.webdriver/languages/plugins`, `window.chrome` 초기화를 통일했다.
  - Cloudflare JS interstitial은 짧게 기다린다. Turnstile/captcha 마커가 보이면 우회하지 않고 `turnstile_present`로 기록한다.
- `scripts/playwright_daemon.py`
  - daemon도 가능하면 system Chrome/Edge executable을 사용하고, 없으면 bundled Chromium으로 fallback한다.
- `probe/fetch_headful.py`
  - headful login/debug path도 같은 Chrome 우선순위와 locale/fingerprint 기본값을 따른다.
- `scripts/probe.py` — **revert됨** (S4-first reorder 미채택, HEAD 복원). 위 원인 #2 참조.
- `probe/diagnose.py`
  - primary target attempts가 모두 404이면 Hcap retry가 WAF 403을 받더라도 `TARGET_NOT_FOUND`로 분류한다.
  - baseline root는 OK인데 target path의 모든 진입이 `BLOCKED_BOT`이면 `ENTRY_BLOCKED`로 분류한다.

## 검증

최종 7-URL probe 결과:

| URL | after verdict | 결과 |
|---|---|---|
| akiba-souken `/anime/` | `BASELINE_BLOCKED` | 회복 없음. DNS 단계 실패라 headless 개선 영역 밖. |
| livechart `/news` | `TARGET_NOT_FOUND` | 개선. S4/현재 static 모두 404로 정정. 등록 대상 아님. |
| melonbooks detail | `BASELINE_BLOCKED` | 회복 없음. TCP reset. age-gate 처리까지 도달 못 함. |
| otaquest `/` | `BASELINE_BLOCKED` | 회복 없음. network timeout. |
| sentai `/blogs/news` | `BASELINE_BLOCKED` | 회복 없음. TLS/connect timeout 또는 reset. |
| skeb `/` | `CLOUDFLARE_PROTECTED_SITE` | 회복 없음. 루트부터 429, Turnstile/Cloudflare 보호. |
| ufotable `/news/` | `ENTRY_BLOCKED` | 개선. 루트 OK + target path 403으로 분류 보류 제거. |

`tests/probe_heuristics/test_headless_browser_profile.py`를 추가했고, `tests/probe_heuristics/test_diagnose_target_not_found.py`에 Hcap WAF 재시도 케이스와 entry-blocked 케이스를 보강했다.

## 트랙 B 검토

이 변경 자체가 트랙 B다. 특정 사이트 selector/config 없이 probe의 headless 진입 프로필, 호출 순서, 차단/404 진단을 일반화했다. 다만 DNS/TCP/TLS reset, Cloudflare Turnstile/429는 정책상 captcha 우회 없이 자동 회복하지 않았다.
