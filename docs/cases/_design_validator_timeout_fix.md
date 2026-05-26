---
slug: infra_validator_timeout_fix
url: internal://validator-timeout
status: "🛠️ validator timeout root-cause + surgical fix design"
outcome: improved
date: 2026-05-26
fix_layer: F
failure_keys:
  - validate_internal_timeout
  - validator_timeout_misclassified
tags:
  - infra
  - validator
  - agentic
---

# Validator Timeout Root Cause + Fix Design

## Phase 1 — root cause

Observed failure pattern: agentic registration candidates often validate through `scripts/validate_config.py`, which wraps `generate.validate.validate_built_config(..., fetch_articles=1)` in a fixed internal timeout. For `playwright_html`, a single validation run can spend the budget before it can return a useful validation report.

Root-cause chain:

1. `validate_config.py` runs in a fresh process for each candidate. That means each candidate creates a fresh adapter and, for `playwright_html`, a fresh Chromium process through `open_session`.
2. `validate_built_config(fetch_articles=1)` currently computes `budget = min(len(posts), max(want + 2, 5))`. With `want=1`, failing or skipped article bodies can trigger up to five `fetch_article` calls.
3. Each Playwright `_goto` pays `page.goto(wait_until="domcontentloaded")`, Cloudflare detection on first goto, `_wait_xhr_quiet`, and optional `wait_for_selector`. The selector wait is intentionally swallowed, but still costs up to `idle_timeout_ms`.
4. The cost multiplies as: browser launch + 1 list goto + up to 5 article gotos. With default runtime patches for generated `playwright_html` configs (`nav_timeout_ms=20000`, `idle_timeout_ms=12000`, `quiet_ms=800`), a bad article selector can consume the validator budget without any single step being an infinite hang.
5. `scripts/register.py` then treats “all agentic attempts ended in `validate_internal_timeout_*`” as `capability_blocked`. That is too broad: a probe verdict of HTTP/headless OK plus validator timeout is not evidence of anti-bot entry blocking. It is usually a slow/expensive generated config or article validation path.

Answers to the requested checks:

- Q1: candidate validation does not reuse Chromium across `validate_config.py` subprocesses. Within one `validate_built_config` call, one adapter session is reused for list and article fetches.
- Q2: the budget loop can burn five article fetches only when no real body verdict is reached, for example repeated exceptions or skip-status/zero-body cases. A good first body breaks after one fetch.
- Q3: `domcontentloaded` is not an infinite wait by itself, but on JS-heavy sites it can combine with quiet/selector waits per goto. Changing the default globally is risky because SPA shells may need DOMContentLoaded semantics.
- Q4: probe verdict HTTP/headless OK does not force `httpx_html`; later generated candidates can still choose `playwright_html` through prompts/escalation hints.
- Q5: `_wait_xhr_quiet` has a 2s default hard cap in engine, but generated Playwright configs are patched in `register.py` to larger values unless already set.
- Q6: `wait_for_selector(..., timeout=idle_timeout_ms)` costs time even when swallowed. This is especially expensive across several article fetches.
- Q7: Playwright launch is per adapter session and per validator subprocess. Process-level reuse would reduce cold start but is outside the current subprocess boundary.
- Q8: `wait_until="commit"` may help specific slow pages, but as a global default it risks capturing pre-hydration shells. If added, it should be opt-in after timing evidence.

## Phase 2 — options

| Option | Change | ROI | Risk | Recommendation |
|---|---|---:|---|---|
| A. Article validation budget | Change the fallback article budget from minimum 5 to `want + 1` spare. For `fetch_articles=1`, try at most 2 article pages. | High | First two bodies may both be restricted/empty, causing a hard fail where the fifth would pass. | Implement first. It keeps one spare while removing most timeout burn. |
| B. Chromium reuse | Reuse a module-level Chromium/browser in `validate_config.py`. | Medium inside one process | Agentic validation often forks fresh subprocesses, so benefit is limited. Storage/cookie isolation must stay context-level. | Defer. Larger change for less guaranteed benefit. |
| C. Prefer `httpx_html` when probe static OK | Bias generated candidate strategy away from Playwright if probe says static HTTP has usable list rows. | Medium | This belongs in prompt/probe signal tuning and may regress real JS-rendered boards. | Defer to a prompt/probe task with batch examples. |
| D. `wait_until` opt-in | Add config option to use `commit` for selected Playwright configs. | Medium | Global default could break SPA hydration. Schema/config surface grows. | Defer until timing traces show navigation dominates. |
| E. Timeout classification | Stop mapping validator-only timeouts to `capability_blocked`. Keep HTTP 403/429/451 as capability-blocked. | High | Some genuinely blocked slow sites become `gen_fail` instead of Later. Probe verdict remains the right source for entry blocking. | Implement first. Fixes the fail-kind bug. |
| F. Timing visibility | Use existing trace spans (`validate_fetch_list`, `validate_fetch_article`) and optionally expose them from the validator CLI. | Medium | More CLI output can break agent JSON parsing if not carefully gated. | Proposal only for now; traces already exist when parent trace is active. |

## First patch

Implement two surgical changes:

1. Option A: `validate_built_config(fetch_articles=1)` should fetch at most two article pages before deciding it cannot obtain a body. This preserves one skip-status spare and removes the five-page burn.
2. Option E: `_generation_error_capability_blocked_reason` should classify HTTP 403/429/451 as capability-blocked, but not validator-only timeout attempts. Those remain `gen_fail`/retryable evidence unless probe entry verdict already produced rc=5.
3. Keep the validator internal cap at 25s. The fix reduces work per candidate instead of extending the timeout ceiling.

No global `wait_until` change in this patch. No Chromium reuse in this patch.

## Instrumentation note

`generate.validate` already emits trace spans for adapter build, list fetch, and each article fetch through `engine.tracing.current_trace()`. If the next batch still shows validator timeouts, the next low-risk instrumentation is a gated `validate_config.py --verbose-timing` mode that keeps stdout JSON-compatible and adds per-span durations to the JSON payload only when explicitly requested.

## Verification plan

- Add a validator unit test proving `fetch_articles=1` only attempts two article fetches when article fetches keep failing.
- Add a classifier unit test proving all-attempt validator timeout no longer becomes `capability_blocked`.
- Run targeted tests:
  - `python tests/validate/test_article_fetch_budget.py`
  - `python tests/scripts/test_capability_blocked_validate_timeout.py`
  - `python tests/fail_taxonomy/test_classify_fail.py`
  - `python tests/llm/test_codex_agentic.py`
- Run required smoke:
  - `python scripts/probe_smoke.py --stage 3 --stage 5`
