---
slug: _generic_agentic_stealth_dns_race_auto_retry
url: (generic)
status: "improved — agentic ERR_NAME_NOT_RESOLVED can auto-retry with disable_stealth"
outcome: improved
fix_layer: F
failure_keys: [agentic_dns_race, err_name_not_resolved, stealth_disable_fallback]
date: 2026-05-27
trigger_slugs: [host_another-eden-jp_news_57af7bcf, host_biathlonworld-c_news_55138d07, host_fate-go-jp_news_92f8d1f5]
related_commits: ["7ee403a"]
---

# Agentic stealth DNS race auto-retry

## root cause

Patchright / `playwright_stealth` can produce a browser-side DNS race where `Page.goto` fails with `ERR_NAME_NOT_RESOLVED` even though OS-level DNS and HTTP checks are healthy. Commit `7ee403a` added the config vocabulary, `disable_stealth: true`, but that was still manual and per-site.

This change generalizes the recovery path: when a probe-grounded `playwright_html` candidate repeatedly fails with browser DNS errors, keep the selector/strategy direction and retry once with top-level `disable_stealth: true`. It does not add site-specific configs for the three trigger slugs.

## fix

- Retry recipe support: `generate/generator.py` adds recipe `stealth_dns_disable`. Repeated Playwright DNS failures select the recipe, inject text feedback, and provide a patched starting candidate with `disable_stealth: true`.
- Agentic prompt: `prompts/register_agent_AGENTS.md` tells the child agent to try the same probe-grounded config with `disable_stealth: true` after repeated DNS failures.
- F-layer: `scripts/register.py` catches agentic `GenerationError` with `max_cycles` / `parent_revalidate_fail` / `agent_gave_up`, patches the preserved `last_config`, validates it once with `disable_stealth: true`, and returns that config only if validation passes. This is the declared fix layer because it is the parent-side enforcement that turns the signal into a recovered config.
- Parent handoff fix: `generate/codex_agentic.py` now carries `candidate.json` as `last_config` even when the final agent JSON is `ok:false, config:{}`. Without this, register cannot apply the fallback to old-style compact agentic failures.

## trigger evidence

Read-only N100 artifact pull was attempted because this worktree had no local `output/` artifacts. The pull populated local ignored `output/` runtime artifacts; N100 code, git, and services were not changed.

Old FAILED markers show the shared pattern:

- `host_biathlonworld-c_news_55138d07`: attempt 2 `ERR_NAME_NOT_RESOLVED on Page.goto`
- `host_fate-go-jp_news_92f8d1f5`: attempts 1 and 2 `ERR_NAME_NOT_RESOLVED`
- `host_another-eden-jp_news_57af7bcf`: same catalog root cause, but current pulled marker has selector 0-row failures and an earlier generic C-layer static-row fix already covers part of this slug.

Old markers have `last_config: {}` because the pre-fix parent discarded `candidate.json` on `ok:false`. That prevents faithful NEW-vs-OLD fallback replay from these artifacts alone; future failures now preserve the candidate for the F-layer retry.

## OLD vs NEW

| path | OLD | NEW |
|---|---|---|
| api-loop retry | Infra DNS feedback said not to switch selector direction, but had no deterministic stealth patch | Repeated Playwright DNS failures select `stealth_dns_disable` and pass a patched starting candidate |
| agentic child | Prompt said infra failure is not selector evidence, but did not name `disable_stealth` | Prompt tells the child to retry same `playwright_html` config with `disable_stealth: true` |
| parent register | Agentic max-cycle DNS failure became `.FAILED.json` | Parent validates a `disable_stealth:true` patched candidate once, publishing only on validation pass |
| agentic error payload | `ok:false, config:{}` lost the last candidate | Parent recovers `candidate.json` into `GenerationError.last_config` |

## Track B 6-layer audit

- E schema 거부: miss — config schema already permits `disable_stealth`; this is not a schema-invalid config problem.
- D retry feedback: hit — repeated validation failures carry enough signal to inject a deterministic retry recipe.
- C probe digest 신호: miss — the probe can recommend Playwright, but the race appears during validation `Page.goto`, after probe digest construction.
- B few-shot: miss — adding examples would not force the fallback when browser DNS fails.
- A system prompt: hit — agentic worker instructions needed the explicit `disable_stealth:true` retry rule.
- F engine/register flow: hit — agentic max-cycle exits need a parent-side enforcement retry because the child may still stop before applying the recipe.

## impact

No config files were changed. Runtime impact is limited to failed generation paths where:

- `last_config.strategy == "playwright_html"`
- `disable_stealth` is not already true
- agentic failure text contains DNS-resolution markers
- the patched candidate passes normal `validate_built_config`

The fallback does not use `headless:false` and does not weaken anti-bot handling for sites whose Playwright validation is already passing.

## deferred

Deferred 0. There is no separate deferred heuristic left by this chunk.

## 회귀 검증

- RED: the new `tests/probe_heuristics/test_retry_recipes.py` recipe cases failed before implementation (`stealth_dns_disable` not selected, patch missing).
- RED: `tests/llm/test_register_auto_mode.py::test_generate_by_mode_revalidates_disable_stealth_after_agentic_dns_race` failed because `_generate_by_mode` had no fallback hook.
- RED: `tests/llm/test_codex_agentic.py` failed because max-cycle `candidate.json` was not carried as `last_config`.
- GREEN targeted tests passed after implementation.
- `python -m pytest tests/llm/test_register_auto_mode.py tests/llm/test_retry_feedback.py -q`: 10 passed.
- `python scripts/probe_smoke.py --stage 3 --stage 5`: PASS 1654 / FAIL 0 / WARN 1.
- `python scripts/vocab_lint.py`: FAIL on 6 pre-existing avoid-term hits in `.claude/skills/hand-config/SKILL.md` and older case files. This case file was fixed after the first lint run and no longer appears in the lint output.

Artifact replay note: old N100 artifacts were pulled, but the old `.FAILED.json` rows have `last_config: {}`. A true live NEW-vs-OLD register replay would require rerunning `register.py` and writing `configs/` / `output/poll_state`, which this codex hard-stop explicitly avoided. Mark N100/live verification pending for Claude review.

## follow-up

After Claude review, run one controlled failed-slug retry in the normal owner workflow and compare whether the fallback publishes a `playwright_html` config with `disable_stealth: true` or leaves a richer `.FAILED.json` containing the failed fallback feedback.
