---
slug: _bug_validate_timeout_shorter_than_tool_2026-05-26
url: internal://agentic-validator-timeout
status: "✅ improved — validator internal timeout now fires before Codex tool timeout"
outcome: improved
date: 2026-05-26
fix_layer: F
failure_keys: [validator_hung_no_json, codex_tool_timeout_before_validator]
config_strategy: none
adapters_changed: []
engine_files_touched: [scripts/validate_config.py, tests/llm/test_codex_agentic.py]
tags: [bugfix, codex, agentic, validate_config, timeout]
---

## Evidence

Retry batch residual failures:

```
3150 attempts: [{"i": 1, "validate_ok": false, "error": "validator hung/no JSON; timed out"}, {"i": 2, "validate_ok": false, "error": "timeout 30s rc=124"}]
3167 attempts: [{"i": 1, ..., "error": "syntax error writing candidate"}, {"i": 2, ..., "error": "validator hang/no result"}]
3169 attempts: [{"i": 1, ..., "error": "validator hung/no JSON result"}]
```

The observed Codex tool failure text was:

```
timeout 30s rc=124
```

Affected URLs:

- job 3150: giantbomb
- job 3167: wingamestore/news
- job 3169: macgamestore/news

## Investigation

Round-1 set `scripts/validate_config.py:INTERNAL_TIMEOUT_S = 60.0`.
That timeout is inside the validator process, but the Codex agent runs the validator through its shell tool.
The observed tool cap is 30 seconds, so the shell tool can kill the validator before the validator emits graceful JSON.

Local `codex exec --help` shows generic `-c key=value` config overrides, but this repo's `run_codex_agentic` command line does not set an exec/tool timeout override. There is no local, repo-owned knob currently wired for this path.

## Fix

`scripts/validate_config.py` now uses:

```
INTERNAL_TIMEOUT_S = 25.0
```

This is below the observed 30-second tool cap, so slow validation returns structured JSON:

```
{"ok": false, "error": "validate_internal_timeout_25s", "checks": [], "sample_posts": []}
```

The agent can then use the failure as feedback instead of seeing a shell timeout with no JSON.

## Regression

`tests/llm/test_codex_agentic.py` now expects the default internal timeout to be 25 seconds and still verifies that a patched 1-second timeout emits JSON with rc=0.
