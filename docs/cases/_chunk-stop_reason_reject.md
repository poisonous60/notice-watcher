---
slug: _chunk-stop_reason_reject
url: ""
status: improved
outcome: improved
fix_layer: A+F
failure_keys: [redundant_classifier_recall, agent_self_veto_missing]
date: 2026-05-25
tags: [system, register, agent_prompt]
---

## 요약

Chunk 1 stop_reason reject gate 개선. api_loop_once / agentic 이 content, not-found, login-required 를 스스로 판정한 경우 `GenerationError.stop_reason` 으로 전달하고, `register.py` 는 `_classify_veto` 재호출 없이 rc=3/4/2 로 바로 거부한다.

## 원인

gen_fail post-mortem 이 `_classify_veto` 를 다시 호출해 content/not_found/login 판정을 기대했다. 하지만 classifier 캐시 hit 또는 저신뢰 판정이면 이미 agent 가 충분한 self-veto 근거를 갖고 있어도 gen_fail rc=1 로 남았다.

## 변경

- A: `prompts/config_writer.system.txt`, `prompts/register_agent_AGENTS.md` 에 self-veto JSON과 `stop_reason` enum을 명시했다.
- F: `generate/generator.py` 가 self-veto sentinel JSON을 `GenerationError.stop_reason` 으로 올리고, `scripts/register.py` 가 stop_reason을 rc로 매핑한다.
- F: `bot/fail_taxonomy.py` 에 agent self-veto subkind를 rc별 fail kind에 추가했다.

## 영향

configs, poll_state, triage output은 건드리지 않았다. 기존 classifier accept-path와 `_CLASSIFY_VETO_CACHE` 는 유지하고, gen_fail 사후 재분류 경로에서만 classifier 재호출을 제거했다.

## 회귀 검증

- `python -m pytest tests/llm/test_register_auto_mode.py tests/fail_taxonomy/ -x`
- `python scripts/probe_smoke.py --stage 3 --stage 5`

## escalate

없음. ALLOW-LIST 밖 변경이나 사이트별 config 변경 없이 공통 stop_reason 전달 경로만 고쳤다.
