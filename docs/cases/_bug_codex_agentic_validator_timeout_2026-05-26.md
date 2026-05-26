---
slug: _bug_codex_agentic_validator_timeout_2026-05-26
url: internal://codex-agentic-validator-timeout-and-cli-transient
status: "✅ fixed"
outcome: improved
date: 2026-05-26
fix_layer: none
failure_keys: [validator_hung, codex_stdin_closed, codex_agentic_transient_timeout]
tags: [bug, codex, agentic, register, validate, infra]
---

## 증상

2026-05-26 games batch (`2026-05-24-games-indie-media-store`, N100 jobs 3048..3147)
에서 agentic `gen_fail` 14건이 같은 infra fault로 묶였다. 사이트별 selector나 probe
판단 실패가 아니라 Codex agentic orchestration/validator 경계에서 멈춘 케이스다.

### Pattern 1: validator hung (8건)

agent `attempts[].error` 에 `validator_hung`, `validate_timeout`, `validator hung/no JSON`,
`no validator output`, `timeout_20s`, `timeout_30s`, `timeout_124s` 류가 남았다.

- job 3052 `opencritic.com` — `validator_hung/timeout_20s`
- job 3053 `opencritic.com/news` — `validate_timeout`
- job 3056 `giantbomb.com` — `validator hung/no JSON`
- job 3078 `game.watch.impress.co.jp` — `no validator output`
- job 3082 `app-liv.jp` — `validator hung/no result`
- job 3088 `thisisgame.com` — `validator_hung/timeout_124`
- job 3090 `gamefocus.co.kr` — `validator_hang`
- job 3145 `macgamestore.com/news` — `validator_hang/timeout_30s`

### Pattern 2: Codex CLI startup timeout (3건)

`register.py` wall deadline 이 먼저 끝났고 stderr tail 은 Codex CLI startup marker
`Reading prompt from stdin...` 만 남았다. 이는 prompt 전달 실패라기보다 CLI가 stdin을
읽은 뒤 모델 호출/네트워크 단계에서 멈춘 transient로 분류한다.

- job 3076 `gamespark.jp` — `codex_agentic timeout after 158.13s`
- job 3112 `donews.com` — `codex_agentic timeout after 153.88s`
- job 3116 `3dmgame.com` — `codex_agentic timeout after 86.22s`

### Pattern 3: Codex CLI exec_command stdin closed (3건)

Codex CLI tool router 가 `write_stdin failed: stdin is closed for this session; rerun
exec_command with tty=true to keep stdin open` 를 냈다. 현재 parent invocation 에서
agent tool session stdin 이 닫힌 transient로 분류한다.

- job 3115 `gamersky.com/news`
- job 3117 `3dmgame.com/news`
- job 3133 `wingamestore.com/news`

## Root cause

`scripts/validate_config.py` 는 `validate_built_config(cfg, digest=None, fetch_articles=1)`
를 직접 `asyncio.run(...)` 으로 실행했다. slow site 에서 list/article fetch 가 내부 timeout
없이 오래 걸리면 Codex tool 실행 시간 제한이 먼저 터지고, agent 는 JSON feedback 대신
validator hang 문자열만 보고 retry cycle 을 소모했다.

Codex CLI timeout 두 패턴은 사이트 fault 가 아니다. startup marker 만 있는 timeout 은
stdin read 이후 모델/API/network 단계가 지연된 transient이고, `stdin is closed for this
session` 은 Codex tool session transport transient다.

## Fix

- `scripts/validate_config.py`: validator 전체를 60초 `asyncio.wait_for(...)` 로 감쌌다.
  timeout 시 stdout 에 valid JSON `{"ok": false, "error": "validate_internal_timeout_60s",
  "checks": [], "sample_posts": []}` 를 내고 rc=0 으로 종료한다. agent 는 tool timeout 대신
  명시적인 validation feedback 을 받고 다음 cycle 을 판단할 수 있다.
- `generate/codex_agentic.py`: Codex CLI timeout stderr 가 startup marker 뿐이면
  `codex_agentic_transient_timeout` 으로 메시지를 구분한다.
- `generate/codex_agentic.py`: `stdin is closed for this session` stderr 는
  `codex_agentic_transient_session_stdin_closed` `LLMNetworkError` 로 분류한다.

## Allow-list self-check

- 변경 파일은 `scripts/validate_config.py`, `generate/codex_agentic.py`,
  `tests/llm/test_codex_agentic.py`, 이 case 파일뿐이다.
- `scripts/register.py`, `prompts/register_agent_AGENTS.md`, configs, recognizers, probe
  heuristics 는 건드리지 않았다.
- probe artifact 는 사용하지 않았다. 세 패턴 모두 site-specific crawl output 이 아니라
  validator/CLI process boundary fault 이므로 probe pull 이 root-cause evidence 가 아니다.
- outcome 은 `improved` 다. 자동 agentic infra 가 같은 unknown site batch에서 더 잘 실패하고
  transient를 더 잘 분류하게 된 generic improvement 이며 `no_change`/`deferred` 가 아니다.

## 회귀 검증

- `python -m pytest tests/llm/test_codex_agentic.py -x` PASS
- `python scripts/probe_smoke.py --stage 3 --stage 5` PASS 1502
