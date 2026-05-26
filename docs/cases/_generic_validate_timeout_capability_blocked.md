---
slug: _generic_validate_timeout_capability_blocked
url: (cross-site)
status: 🧱 영구 게이트 — validate_internal_timeout 전수 = rc=5 capability_blocked
outcome: improved
date: 2026-05-26
fix_layer: F
failure_keys: [validate_internal_timeout, capability_blocked, agentic_validate]
tags: [agentic, capability-blocked, validate-timeout, cross-site, games-indie-studios-asia]
requested_by: hand-config-batch-2026-05-24-games-indie-studios-asia
---

## 트리거 (cross-site)

`2026-05-24-games-indie-studios-asia` batch 에서 동일 fail 신호가 5+ sites:

| slug | url | last_feedback (요약) |
|---|---|---|
| host_gamechangerstud_root_c5e69cfe | https://gamechangerstudio.net/ | `[{i:1,err:validate_internal_timeout_25s},{i:2,...timeout}]` |
| host_gamechangerstud_news_d4cfdcba | https://gamechangerstudio.net/news/ | `[..._timeout_25s, ..._timeout_25s]` |
| host_key-visualarts-_root_5b18021b | https://key.visualarts.gr.jp/ | `[..._timeout_25s, ..._timeout_25s]` |
| host_mojikenstudio-c_root_5aab6877 | https://mojikenstudio.com/ | `[..._timeout_25s, ..._timeout_25s]` |
| host_typemoon-com_root_83103eb7 (혼합) | https://typemoon.com/ | `[invalid_transform, validate_internal_timeout_25s]` |

§0c-0 rubric: 2+ sites 같은 fail_signal → **agentic 자리 박기** (per-site codex X). 위 5건 중 4건 (typemoon 제외) 은 모든 attempt 가 `validate_internal_timeout_<N>s` — agentic 의 `validate_built_config` 가 LLM 이 만든 config 의 fetch_list 를 검증 단계에서 호출했는데 사이트가 25s 안에 응답 못 함.

## 진단

- `scripts/validate_config.py:103` 가 `validate_internal_timeout_<INTERNAL_TIMEOUT_S>s` 토큰을 `attempts[i].error` 로 박는다 (commit 1668f34 hard-timeout validator).
- `generate/codex_agentic.py:820` 가 모든 attempt 실패 시 `last_feedback=json.dumps(attempts)` 로 `GenerationError` raise.
- `scripts/register.py:3188` 의 GenerationError 핸들러는 `_generation_error_capability_blocked_reason(e)` 로 cap_blocked 여부를 판정 후 rc=5 분기. 기존 패턴은 HTTP 4xx (403/429/451) 만.
- validate_internal_timeout 의 *근본 원인* = **LLM 잘못 X, 사이트 응답 지연** (anti-bot 게이트 / 느린 TLS handshake / Cloudflare challenge wait). LLM 이 만든 config 가 옳더라도 fetch_list 가 25s 안에 못 끝남.

분류기 위치 (E/D/C/B/A/F 중): **F (agentic feedback → rc 분류 헬퍼)**. 게이트는 register.py 의 GenerationError 핸들러 자리 — 이미 4xx-cap_blocked 와 같은 라인.

## 무엇을 바꿨나

### 1) `scripts/register.py` — `_generation_error_capability_blocked_reason` 확장

- `_VALIDATE_INTERNAL_TIMEOUT_RE` 정규식 추가.
- `_all_attempts_validate_timeout(last_feedback)` helper — `last_feedback` 이 attempts JSON list 이고, `len>=2` 이고, 모든 entry 의 `error` 가 `validate_internal_timeout_<N>s` 패턴이면 True.
- 보수적 (≥2 attempts, 모든 attempt timeout): typemoon 같은 혼합(LLM hallucination + timeout) 은 cap_blocked 분류 X.
- 매칭 시 reason: `"capability_blocked (validator timed out on every agentic attempt — target site too slow for fetch_list within hard-timeout, likely anti-bot delay or slow TLS handshake)"`.
- 기존 rc=5 분기 (register.py:3205) 가 reason 받아 `_save_failed` + return 5. triage.py pull 의 auto-defer (`_is_capability_blocked`) 가 `reason.startswith("capability_blocked")` 로 Later 큐 자동 이동.

### 2) `bot/fail_taxonomy.py` — 새 Subkind `validate_timeout_all_attempts`

`capability_blocked` FailKind 의 `subkinds` 에 추가. `http_4xx_blocked` 뒤, `entry_blocked` (generic fallback) 앞. 매칭 토큰 = `"validator timed out on every agentic attempt"`.

### 3) `engine/config_schema.py` — pseudo-element selector 거부 (별도 게이트, 같은 commit)

같은 batch 의 whirlpool.co.jp/news/ 가 LLM 이 `::before`/`::after` 류 pseudo-element selector 생성 → `soupsieve.compile` 이 `NotImplementedError` (≠ `SelectorSyntaxError`) raise → 기존 게이트 통과 후 fetch_list 도중 크래시 (`.BUG.json` 또는 traceback). `_check_css_selector` 에 `except NotImplementedError` 추가 — validate_config 시점에 거부 + retry feedback 으로 LLM 회수. 별 Subkind 불필요 (기존 `[FAIL]:CSS 선택자 컴파일 실패` dynamic 이 capture).

## 회귀 검증

- `tests/scripts/test_capability_blocked_validate_timeout.py` — 6 cases (all_timeout/mixed/single/empty/non_json/http_403_regression/timeout_60s).
- `tests/fail_taxonomy/test_classify_fail.py` — `cap_validate_timeout_all_attempts` CASES 항목 추가. 59 PASS.
- `tests/validate/test_selector_compile.py` — `pseudo_element_rejected` 케이스 추가 (whirlpool 재현). 6 PASS.
- `python scripts/probe_smoke.py --stage 3 --stage 5` exit 0. 267/267 configs validate. 1242/1242 heuristic cases.
- `python scripts/gen_fail_taxonomy_doc.py` 실행 → `docs/fail 분류.md` 재생성.

## 일반화 후보

이 fix 자체가 일반화 후보의 *적용*. 다음 batch 의 같은 패턴 사이트는 자동으로 rc=5 cap_blocked → Later. stealth/long-timeout 트랙(별 작업) 으로 회수.

## 후속

- batch 재시도 (`batch-register --failed`) 후 4 sites 가 Later 큐 자동 이동 확인.
- whirlpool retry 시 LLM 이 pseudo-element 없는 selector 로 회수 가능. 실패해도 selector 컴파일 단계에서 retry feedback 발급.
- lenterastudio.com (TCP timeout, dev box 에서도 unreachable) 은 본 게이트와 별개 — probe_timeout = rc=1 path. dev box 에서 dns/tcp 확인 후 REJECTED 박을 것.
