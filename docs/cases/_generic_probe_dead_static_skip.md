---
slug: _generic_probe_dead_static_skip
url: (cross-site)
status: "probe Phase 2 dead-static skip 추가"
outcome: improved
date: 2026-05-27
fix_layer: C
failure_keys: [probe_phase2_oom_on_dead_url, static_uniformly_dead_no_skip, cap_blocked_false_positive]
trigger_batch: 2026-05-24-games-mobile-strategy-rpg
trigger_slugs:
  - vikings.plarium.com
  - gunsofglory.com
  - castleclash.igg.com
  - familyfarmadventure.com/news
  - longtugame.com
  - glu.com/news
tags: [probe, headless, url-dead, capability-blocked, cross-site]
requested_by: hand-config-batch-2026-05-24-games-mobile-strategy-rpg
---

# Generic Probe Dead Static Skip

## 요약

정적 probe 결과가 전부 4xx/5xx/connection-error 인 경우 Phase 2 Playwright headless escalation 을 생략한다.

기존에는 hard login redirect 와 정적 HTML 반복 row 검출만 headless skip 조건이었다. 죽은 URL 또는 서버 오류 URL도 Phase 2 로 넘어가면서 heavy SPA landing, marketing redirect, anti-bot interstitial 에서 RSS memory guard self-kill 로 이어졌고, `register.py` 가 이를 rc=5 capability_blocked 로 분류했다. 실제 원인은 url_dead 또는 정적 entry failure 인데 Later 큐로 잘못 남는 false positive 였다.

## 트리거

`2026-05-24-games-mobile-strategy-rpg` batch drain 뒤 10개 실패 중 8개 url_dead + 2개 anti-bot 성격의 사이트가 rc=5 capability_blocked 로 묶였다.

| slug/host | 관측 | 기대 분류 |
|---|---|---|
| `vikings.plarium.com` | root/news 모두 connect refused/dropped | url_dead |
| `gunsofglory.com` | 200 tiny JS redirect to `/lander`, board 없음 | url_dead |
| `castleclash.igg.com` | 403 Forbidden anti-bot | capability_blocked |
| `familyfarmadventure.com/news` | connect dropped | url_dead |
| `longtugame.com` | persistent 503 | url_dead |
| `glu.com/news` | 404 EA site | url_dead |

이 case 는 per-site config 작성이 아니라 probe escalation gate + dead-network verdict 개선이다. `configs/`, recognizer, prompt, strategy 변경 없음.

## 원인

`scripts/probe.py` Phase 2 skip gate 가 다음 두 조건만 보았다.

- 모든 정적 결과가 hard `LOGIN_REQUIRED` redirect
- 정적 HTML 에 이미 반복 article link rows 존재

전부 404/503/connect-error 인 경우에도 headless 로 넘어갔다. 그 결과 headless child 가 heavy SPA/landing shell 로 진입하고 memory guard 가 rc=99 로 종료하면, `scripts/register.py` 의 `ProbeMemoryGuardError` handler 가 rc=5 capability_blocked 로 저장했다.

Phase 2 를 생략해도 순수 connection-refused baseline 은 기존 `probe.diagnose` 에서 `BASELINE_BLOCKED` 로 남아 `register.py` 의 fallback rc=5 로 갈 수 있었다. dead host 는 catalog URL 수정 대상이므로 기존 url_dead verdict 인 `CERT_OR_DNS_BROKEN` 경로로 보내야 한다.

## 변경

`scripts/probe.py` 에 `_static_results_are_uniformly_dead(static_results)` 를 추가했다.

- empty input 은 False.
- 하나라도 `Classification.OK` 또는 `Classification.LOGIN_REQUIRED` 이면 False.
- 각 결과가 4xx, 5xx, 또는 `status is None/0 + Classification.UNKNOWN_ERROR` 인 경우에만 True.
- True 면 Phase 2 headless 를 생략하고 기존 digest/register policy path 로 넘긴다.

`probe/diagnose.py` 의 기존 `CERT_OR_DNS_BROKEN` 판정에는 `ConnectError` / connection-refused marker 를 추가했다. `scripts/register.py` 의 해당 policy message 도 `SSL/DNS/connect` 로 맞췄다. 최종 mapping 은 기존 `cert_or_dns_broken` → rc=4 `_save_rejected` 경로를 그대로 사용한다.

## Track B 6-layer audit

- E schema 거부: miss - config schema 검증 전 probe escalation 단계 문제.
- D retry feedback: miss - generated config feedback 이전에 probe 가 OOM 으로 종료됨.
- C probe digest 신호: hit - 정적 probe result matrix 만으로 headless escalation 생략 여부를 결정하고, baseline connect failure 를 url_dead verdict 로 분류.
- B few-shot: miss - config 예제로 해결할 생성 문제가 아님.
- A system prompt: miss - LLM 입력 전 probe 실행 제어 문제.
- F engine code: miss - engine strategy/adapters/recognizers 변경 없이 probe CLI gate 로 충분.

## 영향 범위

- `scripts/probe.py`: Phase 2 전 정적 결과가 uniformly dead/error 인지 검사.
- `probe/diagnose.py`: baseline connect failure 를 기존 url_dead verdict 로 분류.
- `scripts/register.py`: rc=4 policy message 를 SSL/DNS/connect 로 표현.
- `tests/probe/test_dead_static_skip.py`: helper 단위 fixture 추가.
- `tests/probe_heuristics/test_diagnose_dead_network_url_dead.py`: connection-refused baseline 이 `CERT_OR_DNS_BROKEN` verdict 로 가는지 확인.
- `docs/cases/_generic_probe_dead_static_skip.md`: 본 case 기록.

영향 사이트는 정적 probe 가 4xx/5xx/network error 만 반환하는 dead URL 또는 entry-blocked URL이다. 정적 200 OK, login redirect, 정적 row 검출 경로는 기존 gate 를 유지한다.

## 회귀 검증

이 codex chunk 는 `scripts/cases_index.py`, DB backfill, `docs/cases/INDEX.md` sync, N100 artifact pull, commit/push/deploy 를 하지 않는다.

검증 예정:

- `python -m py_compile scripts/probe.py`
- `python tests/probe/test_dead_static_skip.py`
- `python scripts/probe_smoke.py --stage 3 --stage 5`
- dead static helper fixture: all 404, all 503, connect error, mixed OK, login, empty input
- local dummy probe: `http://127.0.0.1:9/news` 가 Phase 2 skip message 를 출력하고 headless 를 실행하지 않음
