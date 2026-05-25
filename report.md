## S1 implementation

- `scripts/register.py:68,77` now imports the agentic default timeout as `DEFAULT_AGENTIC_TIMEOUT_S` and defines `MIN_AGENTIC_TIMEOUT_S = 30.0`.
- Before: `_gen_agentic` always let `generate.codex_agentic.run_codex_agentic` use its own default 180s timeout, so a late `register.py` wall deadline could be overrun.
- After: `_gen_agentic(..., wall_deadline=None)` keeps the default 180s behavior; with a wall deadline it uses `min(DEFAULT_AGENTIC_TIMEOUT_S, _remaining_budget(wall_deadline, reserve_s=10.0))`, rejects budgets below 30s with `RegisterTimeoutError`, and passes `timeout_s` into `_run_codex_agentic` (`scripts/register.py:1677,1703-1715`).
- `_generate_by_mode` now accepts `wall_deadline` and forwards it only to agentic paths, including auto escalation (`scripts/register.py:1873-1905`); the main register flow passes the existing `wall_deadline` into `_generate_by_mode` (`scripts/register.py:2993-3000`).
- Regression coverage added in `tests/llm/test_register_auto_mode.py:71,87,102` for default timeout, tight deadline capping, and too-small budget rejection.

## S2 implementation

- `dashboard/usage_view.py:136` adds `agentic_recent`, a read-only query against the existing `llm_calls` schema, filtering `call_site = 'config_generate_agentic'`, ordering by `rowid DESC`, and returning timestamp, slug, status, turns, prompt tokens, completion tokens, latency, and cost.
- `/jobs` now loads recent local agentic usage from `output/usage.sqlite3` without blocking the jobs table if the usage DB is absent or unreadable (`dashboard/app.py:510-527`).
- `dashboard/templates/jobs.html:78-118` renders the new Agentic usage table below the existing jobs table.
- `scripts/dashboard.py:42-58` adds `--self-check`, which imports `dashboard.app` and verifies `/jobs` and `/usage` routes without requiring `DEPLOY_HOST`.
- Schema note: the actual usage table is `llm_calls` (`generate/usage_recorder.py`), not `usage`; no schema migration was added.

## M1 review

Recommendation: defer implementation until concurrency impact is measured.

Findings:
- There is no `chromium_lock` symbol in the inspected paths; the active lock in agentic generation is `_per_slug_lock`, a per-slug filesystem lock (`generate/codex_agentic.py:267-294`).
- Current lock scope covers Codex thinking, process execution, and post-audit because `proc.communicate(..., timeout=timeout_s)` runs inside `with _per_slug_lock(...)` (`generate/codex_agentic.py:579-640`).
- Parent validation runs after the lock is released (`generate/codex_agentic.py:642,710`), so the expensive fresh fetch is already outside the per-slug lock.
- Unlocking before agent thinking would mainly allow two same-slug agentic runs to race on later publish/audit attribution. If a wider Chromium pool lock exists elsewhere, the right design is split lock scopes: no browser/pool lock during Codex thinking, reacquire only around `validate_built_config`, then publish under a per-slug publish lock.

Race notes:
- Reacquire can starve if pool size is 1 and many validates queue, but that is preferable to holding a scarce browser slot for up to the agent timeout.
- For same slug, publish must stay serialized. Releasing the per-slug lock around thinking is not safe unless output publish is protected by a separate final compare/publish lock.

## M2 review

Recommendation: defer embeddings; first improve the cheap scorer if examples quality is poor in measured agentic runs.

Current state:
- `_score_example` documents recognizer +10, eTLD+1 host +5, strategy +3, URL path shape +2, but implementation currently applies only recognizer, eTLD+1, and strategy (`generate/codex_agentic.py:325-346`).
- `_pick_examples` ranks existing `configs/*.json`, excludes the current slug, and copies only the top two into the agent workdir (`generate/codex_agentic.py:349-366,417-434`).

Tradeoff:
- Embeddings could improve cross-host structural similarity, but they add model/API cost and another failure surface before every agentic run.
- The current cheap scorer is deterministic, offline, and likely enough for first-pass grounded generation. The documented-but-missing path-shape axis should be fixed before adding embeddings.

## M3 review

Recommendation: implement later only if false escalation rate is high; current auto escalation is conservative enough for opt-in agentic.

Current state:
- `auto` runs `api_loop` once, calls `_generation_failure_reject_rc`, and only escalates to agentic if the failure is not decisively rejected (`scripts/register.py:1887-1905`).
- Decisive rejection uses the classifier result and deliberately disables the older heterogeneous-hub gate in the auto pre-agentic step (`scripts/register.py:1846-1868,1891-1898`).
- The failure packet contains only compact evidence: source, attempt, candidate config, validation feedback, and error text (`scripts/register.py:1834-1844`).

Gap:
- The auto path does not explicitly distinguish "actionable for agentic" from "non-decisive but probably useless"; it treats all non-decisive api-loop failures as worth one agentic attempt.
- False positives cost one Codex run; false negatives would skip the main benefit of agentic mode. Given default remains `api_loop` and agentic is opt-in, biasing toward escalation is acceptable for now.

## L1 review

Recommendation: design a Linux-only sandbox branch after N100 measurement, not in this task.

Current state:
- ADR 0020 assumes Windows sandbox protection is effectively zero and intentionally uses `--dangerously-bypass-approvals-and-sandbox` with prompt, AGENTS.md, audit, and parent validation as guards.
- Current code always passes `--dangerously-bypass-approvals-and-sandbox` to `codex exec` (`generate/codex_agentic.py:579-594`).
- `codex exec --help` on this dev box exposes `--sandbox read-only|workspace-write|danger-full-access`, `--add-dir`, and `--dangerously-bypass-approvals-and-sandbox`.

Proposed Linux path:
- Branch on platform: keep Windows bypass path unchanged; on Linux, call `codex exec -C <workdir> --sandbox workspace-write --add-dir <workdir>` and omit bypass.
- Keep the existing post-run audit and parent validation even if sandbox works; sandbox becomes defense-in-depth, not the trust anchor.
- Validate on N100 with a probe script that attempts writes inside workdir, repo root, configs, output, and an external temp path, then records whether each is blocked.

Jailbreak note:
- N100 is Linux headless production. If Linux sandbox works, it reduces accidental or hostile writes outside the agent workdir. It does not remove the need for tmpdir-only publish and audit because model/tool behavior and CLI semantics can change.

## Verification

- PASS: `python -m py_compile scripts/register.py generate/codex_agentic.py scripts/dashboard.py` exited 0.
- PASS: `python -m pytest tests/llm/test_codex_agentic.py tests/llm/test_register_auto_mode.py -x` exited 0; pytest collected 3 deadline tests from `test_register_auto_mode.py` and all passed. `test_codex_agentic.py` remains script-style and has no pytest-collected tests.
- PASS: `python scripts/probe_smoke.py --stage 3 --stage 5` exited 0: stage 3 `257 / 257 OK`, stage 5 `103 files / 1187 cases / 0 FAIL`, summary `PASS 1445 FAIL 0 WARN 0 SKIP 0`. It printed existing tracking warnings after the summary about a closed database connection.
- PASS: `python scripts/dashboard.py --self-check` exited 0: `dashboard.app import + /jobs,/usage routes`. It printed an existing FastAPI deprecation warning for `Query(..., regex=...)` in `/runs`.
- PASS: `python scripts/vocab_lint.py` exited 0: scanned 345 files, 23 high-confidence rules.
- Extra sanity: `python tests/llm/test_codex_agentic.py` exited 0 with 19 script-style checks passing.
- Extra sanity: `python tests/llm/test_register_auto_mode.py` exited 0 with 13 script-style checks passing.
