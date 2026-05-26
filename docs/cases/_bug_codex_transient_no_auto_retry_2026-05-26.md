---
slug: _bug_codex_transient_no_auto_retry_2026-05-26
url: internal://codex-agentic-transient-retry
status: "✅ improved — known transient Codex CLI session faults retry once"
outcome: improved
date: 2026-05-26
fix_layer: F
failure_keys: [codex_agentic_transient_session_stdin_closed, no_auto_retry]
config_strategy: none
adapters_changed: []
engine_files_touched: [generate/codex_agentic.py, tests/llm/test_codex_agentic.py]
tags: [bugfix, codex, agentic, transient, retry]
---

## Evidence

Retry batch jobs 3148, 3149, 3157, 3164, 3165, and 3166 all had the same transient pattern:

```
2026-05-26T...Z ERROR codex_core::tools::router: error=write_stdin failed: stdin is closed for this session; rerun exec_command with tty=true to keep stdin open
```

The classifier already recognized this as:

```
codex_agentic_transient_session_stdin_closed
```

But the same sites failed across two batches, which showed classification alone was not recovery.

## Investigation

`generate/codex_agentic.py:_codex_classify_error` turns the stderr into `LLMNetworkError`.
`scripts/register.py:_gen_agentic` catches `LLMError` and translates it into `GenerationError`, which then becomes rc=1 gen_fail.

There was no retry between "known transient session fault" and "record gen_fail".
Retrying in bot/worker or `batch-register` would complicate queue semantics. Retrying in `run_codex_agentic` is narrower and recreates a fresh workdir/subprocess.

## Fix

`run_codex_agentic` is now a wrapper over one-shot `_run_codex_agentic_once`.
It retries once for known transient `LLMNetworkError` messages:

- `codex_agentic_transient_session_stdin_closed`
- `codex_agentic_transient_timeout`

If the second attempt fails, the original error class path is preserved and the operator can still run a human-directed retry batch.

## Regression

`tests/llm/test_codex_agentic.py` now simulates a first Codex subprocess returning `stdin is closed`, then a second subprocess returning valid output. The test verifies two subprocess attempts and successful result metadata.
