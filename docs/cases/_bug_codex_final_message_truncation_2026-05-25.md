---
slug: _bug_codex_final_message_truncation_2026-05-25
url: internal://codex-agentic-final-message-truncation
status: "✅ fixed (merged fecb54c, deployed to N100)"
outcome: improved
date: 2026-05-25
fix_layer: none
failure_keys: [llm_parse, codex_final_message_truncated, candidate_json_recovery]
tags: [bug, codex, agentic, register]
---

## 실측 회복 (fix 후 retry)

| slug | 1차 batch | retry 후 | n_baseline |
|---|---|---|---|
| densediscovery.com | rc=1 LLMParseError (char 1083 mid-string 잘림) | ✅ done | 30 |
| webtoolsweekly.com | rc=1 LLMParseError | ✅ done | 20 |
| nodeweekly.com | rc=1 LLMParseError (char 1045 잘림) | ✅ done | 4 |
| postgresweekly.com | rc=1 LLMParseError | ✅ done | 4 |

## 요약

Chunk 5 substack batch 에서 `last.json` 이 약 1KB 지점에서 mid-string 으로 잘리고
`LLMParseError: Expecting ',' delimiter` 로 실패했다. subprocess rc=0 이라 CLI 자체는
성공 종료했지만, parent 가 읽는 최종 assistant payload 가 JSON 으로 완결되지 않았다.

Root cause 는 "Codex final message 에 full config 를 다시 echo 하게 한 출력 계약"이다.
`candidate.json` fallback 은 잘린 final JSON 에서 config 만 복구할 수 있지만,
정상 경로가 여전히 final message 의 `config` 필드를 요구하면 `attempts`/`stop_reason`
보존과 parse 안정성이 final assistant 출력 길이에 계속 묶인다.

## 조사 근거

- Codex CLI `--output-last-message` 는 마지막 agent message 문자열을 파일에 쓰는 기능이다.
  별도 JSON 복구 루프가 아니라 `last_agent_message.unwrap_or_default()` 를 그대로 write 한다.
  Source: <https://github.com/openai/codex/blob/9f42c89c0112771dc29100a6f3fc904049b2655f/codex-rs/exec/src/event_processor.rs#L31-L44>
- `--json` 의 `turn.completed.usage` 는 final text 와 별개로 token usage notification 에서 온다.
  usage notification 이 없으면 default usage 가 나올 수 있다. 따라서 `prompt_tokens=0`
  `completion_tokens=0` 은 "최종 메시지가 짧아야 한다"는 보장은 아니다.
  Source: <https://github.com/openai/codex/blob/9f42c89c0112771dc29100a6f3fc904049b2655f/codex-rs/exec/src/event_processor_with_jsonl_output.rs#L117-L126>
- Codex JSONL processor 는 turn items 에서 final agent message 를 고른다.
  Source: <https://github.com/openai/codex/blob/9f42c89c0112771dc29100a6f3fc904049b2655f/codex-rs/exec/src/event_processor_with_jsonl_output.rs#L378-L390>
- OpenAI Responses API 의 `max_output_tokens` 는 visible output 과 reasoning tokens 를 함께 포함하는 상한이다.
  Source: <https://developers.openai.com/api/reference/resources/responses/methods/create>
- 현재 조사한 Codex source 의 `ResponsesApiRequest` 에는 `max_output_tokens` 필드가 없다.
  즉 `-c max_output_tokens=...` 또는 `model_max_output_tokens` 류 설정을 이 경로의 확정
  완화책으로 볼 근거가 없다.
  Source: <https://github.com/openai/codex/blob/9f42c89c0112771dc29100a6f3fc904049b2655f/codex-rs/codex-api/src/common.rs#L169-L190>
- Codex config 의 `model_context_window` / `model_auto_compact_token_limit` 는 context
  window/auto-compaction 설정이고, `tool_output_token_limit` 는 tool output history budget 이다.
  final assistant message 를 full config echo 에 충분하게 만드는 보장으로 쓰면 안 된다.
  Source: <https://www.mintlify.com/openai/codex/configuration/reference>
- OpenAI model docs 는 GPT-5.5, GPT-5.4, GPT-5 의 큰 max output cap 을 보여주지만,
  이는 API 모델 상한이지 Codex CLI final-message 계약 안정성을 보장하는 값이 아니다.
  Source: <https://developers.openai.com/api/docs/models/compare>, <https://developers.openai.com/api/docs/models/gpt-5>

## Fix design

출력 계약을 바꾼다.

- Agent 는 full config 를 final message 에 echo 하지 않는다.
- Agent 는 항상 `./candidate.json` 을 쓴다.
- 성공 final JSON 은 `{"ok":true,"candidate_path":"./candidate.json","config":{},...}`
  형태의 작은 envelope 만 낸다.
- Parent 는 `ok=true` 이고 `config` 가 없거나 비어 있으면 `candidate_path` 를 읽는다.
- Parent 는 agent 를 신뢰하지 않고 기존처럼 `validate_built_config` 로 재검증한다.
- `candidate_path` 는 `candidate.json` / `./candidate.json` 만 허용한다. tmpdir 밖 경로는 거부.

이 방식은 모델/CLI output cap, tool-active 여부, usage event 누락 여부와 독립적이다.

## 변경 파일

- `generate/codex_agentic.py`
  - `ok=true` final envelope 의 `candidate_path` 지원.
  - `candidate_path` allow-list 후 `./candidate.json` 로드.
  - 기존 truncated `last.json` fallback 은 유지.
- `prompts/register_agent_AGENTS.md`
  - success final output 도 full config echo 금지.
  - `candidate_path` envelope 를 명시.
- `prompts/register_agent_user.txt`
  - 같은 출력 계약을 짧게 반복.
- `tests/llm/test_codex_agentic.py`
  - final message 가 `candidate_path` 만 담아도 parent 가 config/attempts/stop_reason/usage 를
    보존하는 regression test 추가.

## 자가 점검

1. 어느 자리? none — hand-config E/D/C/B/A/F taxonomy 밖의 Codex agentic output-contract 변경.
2. 이전 케이스 있나? 이번 chunk trace 의 `LLMParseError`/mid-string truncation 이 직접 재현 신호.
3. 누구 깰까? agentic register 경로만 영향. legacy final JSON 의 full `config` 도 계속 허용한다.
4. 회귀 검증? `python tests/llm/test_codex_agentic.py` red-green 확인.
5. case 파일? 이 파일.
6. 새 strategy/heuristic fixture? 아님. CLI final envelope parser 회귀 테스트로 충분.
7. 일반화 안 되는 이유: site-specific hand config 문제가 아니라 Codex agentic output contract 문제.

## 회귀 검증

- RED: `python tests/llm/test_codex_agentic.py` 실패.
  - 실패: `GenerationError: agent did not produce a passing config (stop_reason='validate_pass')`
- GREEN: `python tests/llm/test_codex_agentic.py` 통과.
  - `24 passed`

## 보류/비채택

- `tool_output_token_limit=20000`: tool output budget 이라 final assistant JSON truncation 의 근본 해결 X.
- `model_auto_compact_token_limit`: context compaction knob 이라 final response payload 크기 해결 X.
- profile/reasoning/model 상향: 품질·추론량에는 영향 가능하지만, full config echo 를 요구하는 계약의
  fragility 를 제거하지 못함.
- `--output-schema`: 이 repo 는 arbitrary config keys 때문에 이미 제거된 상태. schema enforcement 에
  기대면 tool/MCP active session 호환 리스크를 다시 키운다.
