# 2026-05-25 register `auto` mode rollout note

## Summary

`config_generate__mode=auto` was added as the default register generation mode after
the initial agentic rollout.

Goal:

- Keep easy sites cheap: try the existing API-loop generator once.
- Keep hard sites capable: escalate to Codex agentic only after that one-shot fails.
- Avoid wasting agentic work on non-board pages: if the page-type classifier
  decisively says the URL is `content`, `not_found`, `login`, or `catalog`, save
  the registration as `REJECTED` instead of escalating.

Commit:

- `e352395 feat: add auto register generation mode`

N100 status at rollout:

- Code deployed by `scripts/n100_deploy.sh`.
- N100 HEAD after deploy: `e352395`.
- Runtime routing pushed to N100:

```json
{
  "config_generate": "codex:gpt-5.4-mini#low",
  "config_retry": "codex:gpt-5.4-mini#low",
  "config_generate__mode": "auto"
}
```

`output/llm_routing.json` is ignored by git, so the runtime routing push was done
separately with `python scripts/push.py routing`.

## Behavior

Generation mode is selected in `scripts/register.py`:

1. `api_loop`
   - Existing behavior.
   - Runs `generate_config_validated(..., max_attempts=args.max_attempts)`.

2. `agentic`
   - Runs `generate/codex_agentic.py` directly.

3. `auto`
   - Runs API-loop once: `generate_config_validated(..., max_attempts=1)`.
   - If that succeeds, registration continues without agentic.
   - If it fails, run the page-type classifier post-mortem.
   - If classifier evidence is decisive non-index, write `REJECTED` and return
     the corresponding rc.
   - Otherwise escalate to agentic with a compact `failure_packet.json`.

Important detail:

- `auto` does **not** apply the older heterogeneous-hub post-mortem gate before
  agentic. That gate remains for final API-loop generation failures, but auto
  only rejects before agentic when the LLM classifier is decisive. This avoids
  blocking hard-but-possibly-valid sites too early.

## Failure Packet

When `api_loop_once` fails and auto escalates, the agentic workdir may contain:

```text
failure_packet.json
```

It includes:

- `source: api_loop_once`
- `attempt: 1`
- `candidate_config`
- `validation_feedback`
- `error`

The agent prompt tells Codex to treat this as diagnostic evidence only. It may
reuse, patch, or discard the candidate.

## Routing And Dashboard

Allowed `config_generate__mode` values are now:

- `api_loop`
- `auto`
- `agentic`

Dashboard validation rejects `auto` unless `config_generate` uses provider
`codex`, matching the existing agentic restriction.

The `/control` routing UI now persists `auto` and exposes it in the mode list.

## Files Changed In Rollout Commit

- `scripts/register.py`
  - Added `_select_generation_mode`.
  - Added `_generate_by_mode`.
  - Added `_generation_failure_reject_rc`.
  - Added `_build_failure_packet`.
  - Wired main generation dispatch through mode selection.

- `generate/routing.py`
  - Added `auto` to the mode sidecar whitelist.

- `generate/codex_agentic.py`
  - Writes optional `failure_packet.json` into the agent tmpdir.

- `prompts/register_agent_AGENTS.md`
- `prompts/register_agent_user.txt`
  - Documented how the agent should read `failure_packet.json`.

- `dashboard/control_actions.py`
  - Added `auto` validation and UI persistence.

- Tests:
  - `tests/llm/test_register_auto_mode.py`
  - `tests/llm/test_routing.py`
  - `tests/llm/test_codex_agentic.py`

## Verification Performed

On dev box before push:

```bash
python tests/llm/test_routing.py
python tests/llm/test_register_auto_mode.py
python tests/llm/test_codex_agentic.py
python tests/classify/test_classify_index_content.py
python -m py_compile scripts/register.py generate/routing.py generate/codex_agentic.py dashboard/control_actions.py
python scripts/probe_smoke.py --stage 3 --stage 5
python scripts/vocab_lint.py
git diff --check
```

Pre-push hook also passed:

```bash
python scripts/probe_smoke.py --stage 3 --stage 5
```

On N100 after deploy:

```bash
cd ~/notice-watcher
. .venv/bin/activate
python tests/llm/test_register_auto_mode.py
```

Result: 9 passed.

N100 routing resolve check:

```text
codex gpt-5.4-mini {'mode': 'auto'}
```

## Notes For Next Session

- If a user registration is easy, `auto` should usually finish after the single
  API-loop attempt.
- If a user gives a content/article URL and the classifier is confident, it
  should become `REJECTED`; agentic should not run.
- If the classifier is uncertain, agentic should still run even when structural
  hub heuristics look suspicious.
- Existing dirty config changes at rollout time were intentionally not touched:
  four tracked config deletions and one untracked Django config existed before
  this work.

