---
slug: _bug_audit_pyc_false_positive_2026-05-26
url: internal://register-agentic-audit-pyc
status: "✅ improved — Python bytecode/cache rewrites ignored by agent audit"
outcome: improved
date: 2026-05-26
fix_layer: F
failure_keys: [register_audit_violation_false_positive, pyc_recompile_noise]
config_strategy: none
adapters_changed: []
engine_files_touched: [generate/codex_agentic.py, tests/llm/test_codex_agentic.py]
tags: [bugfix, codex, agentic, audit, pycache]
---

## Evidence

Retry batch jobs 3153 and 3154:

```json
{
  "rc": -4,
  "reason": "register_audit_violation: agent wrote outside its workdir",
  "tail": "violations=['/home/aaaa/notice-watcher/scripts/__pycache__/register.cpython-313.pyc (CONTENT CHANGED)']"
}
```

Affected URLs:

- job 3153: gamespark.jp
- job 3154: game.watch.impress.co.jp

## Investigation

`generate/codex_agentic.py:_audit_snapshot_paths` snapshots guarded repo areas including `scripts/`.
`_audit_diff` compares pre/post SHA and size, and any shared-dir content change becomes an audit violation.

That is correct for source files, prompts, configs, tests, docs, and runtime state. It is too strict for Python bytecode:
after deploy, the first `register.py` import can recompile stale `scripts/__pycache__/register.cpython-313.pyc`.
That write is caused by the Python runtime, not by the Codex agent writing outside its tmpdir.

## Fix

`generate/codex_agentic.py` now ignores runtime cache paths in both snapshot and diff:

- `__pycache__`
- `*.pyc`
- `*.pyo`
- `.pytest_cache`
- `.mypy_cache`
- `.ruff_cache`
- `.DS_Store`
- `Thumbs.db`

The audit still detects real source changes in the same guarded directories.

## Regression

`tests/llm/test_codex_agentic.py` now mutates a fake `scripts/__pycache__/register.cpython-313.pyc` and a real `scripts/real_violation.py` in the same diff. The pyc change is ignored and the real source change remains a violation.
