# Agentic Probe Evidence Grounding

Date: 2026-05-27

Related commit: `00f62e2 fix validator probe grounding`

## Summary

This change adds a validator-side guardrail for agentic-generated configs.

The problem was not that a bad URL or bad selector is always slow. The slow path
appears when a generated `playwright_html` candidate opens a page successfully
and then waits for a selector that never appears. The old validator could spend
the internal 25s budget in Playwright waits and return only a generic timeout.

The new guard checks the generated candidate against probe evidence before live
network/browser validation. If the candidate contradicts complete probe HTML or
captured article API evidence, validation fails quickly with a specific
`probe_grounding_*` check. That feedback goes back into the agentic retry loop.

This is not a hard strategy override and not an exact allowlist. It does not
force `httpx_html` or ban synthesized selectors. A synthesized selector is fine
when it actually matches the probe HTML.

## Files

| file | role |
|---|---|
| `generate/validate.py` | Adds `_add_probe_grounding_checks(...)` and calls it after `make_adapter(...)`, before `fetch_list`. |
| `scripts/validate_config.py` | Loads `validator_digest.json` or `digest.json` beside the candidate and passes it into `validate_built_config`. |
| `generate/codex_agentic.py` | Stages compressed `digest.json` for the child model and full `validator_digest.json` for the validator wrapper. |
| `prompts/register_agent_AGENTS.md` | Tells the child agent how to react to `probe_grounding_*` feedback. |
| `tests/validate/test_probe_grounding_guard.py` | Locks fail-fast and fail-open behavior. |
| `tests/scripts/test_validate_config_digest.py` | Locks digest loading behavior for the CLI wrapper. |
| `docs/cases/_design_validator_timeout_fix.md` | Historical case log entry for the timeout investigation. |

## Validation Flow

Normal parent path:

```text
probe -> digest -> config generation -> validate_built_config(cfg, digest)
                                      -> make_adapter / schema check
                                      -> probe grounding guard
                                      -> live fetch_list / fetch_article
```

Agentic child path:

```text
_setup_workdir(...)
  digest.json            # compressed; model reads this
  validator_digest.json  # full; validate_config.py reads this
  candidate.json
  validate_config.py

child runs ./run_validator.* ./candidate.json
  -> validate_config.py loads validator_digest.json
  -> validate_built_config(cfg, digest=validator_digest)
```

## Guard Checks

The guard can emit these hard failures:

| check | when it fires |
|---|---|
| `probe_grounding_list_row_selector` | `list.row_selector` matches 0 nodes in complete `list_html`. |
| `probe_grounding_list_wait_selector` | `playwright_html` `list.wait_selector` matches 0 nodes in rendered list evidence. |
| `probe_grounding_article_wait_selector` | `playwright_html` `article.wait_selector` matches 0 nodes in rendered article evidence. |
| `probe_grounding_article_content_selector` | HTML article content CSS selectors all match 0 nodes in complete article evidence. |
| `probe_grounding_article_json_api` | `article.fetch_kind=json` uses a URL template outside useful captured `article_sample.api_candidates`. |

## Fail-Open Rules

These rules are the safety valve that keeps existing config generation from
being over-constrained:

- No digest passed in: old behavior. Existing config validation and polling do
  not get this guard.
- Malformed or missing `digest.json` / `validator_digest.json`: fail open.
- `list_html` or `article_sample.html` is marked `truncated`: fail open for
  negative selector evidence.
- Agent prompt-compressed HTML is marked `prompt_compressed`: fail open.
- Playwright selector negatives only use rendered evidence:
  - list: `list.html` or `list.captured.html`
  - article: `article_click.html` or `article.captured.html`
- Empty `article_sample.api_candidates` is unknown, not negative evidence.
- JSON article API grounding only fails when useful body API candidates exist.
- `article.body_empty_acceptable=true` skips the article content selector
  negative check.

## Why This Should Not Break Existing Config Creation

Existing configs are not blocked just because this guard exists.

The guard only runs when `validate_built_config` receives a digest. Runtime
polling and plain config loading do not pass probe digest evidence, so their
behavior is unchanged.

For automatic generation, the guard rejects only candidates that contradict
evidence the probe already captured. It does not require selectors to be copied
verbatim from probe candidates. For example, an agent may still create a more
specific selector such as `article.card a[href*='/news/']`; it passes as long as
that selector matches the probe HTML.

The risky cases identified by review were intentionally made fail-open:
compressed prompt HTML, truncated HTML, static fallback HTML for Playwright, and
missing API candidates are not used as hard negative evidence.

What can be newly rejected:

- A generated selector that matches 0 nodes in complete probe evidence.
- A Playwright wait selector that would otherwise burn `idle_timeout_ms`.
- A JSON article endpoint invented outside captured useful article API evidence.

Those are the candidates we want the agent to rewrite rather than validate
slowly.

## Effect On Agentic Quality

This does not make the model intrinsically smarter and does not add new site
evidence. It improves the effective generation loop:

1. Bad candidates fail in tens of milliseconds instead of timing out near 25s.
2. Feedback is specific (`probe_grounding_list_wait_selector`, etc.).
3. The agent retry can choose a selector/API grounded in `digest.json` instead
   of trying the same invented selector with longer waits.

So the expected benefit is better latency and better retry direction, not a
guarantee that every SPA config can be generated.

## Verification From Implementation Session

Local tests run:

```text
python tests/validate/test_probe_grounding_guard.py
python tests/scripts/test_validate_config_digest.py
python tests/validate/test_article_fetch_budget.py
python tests/scripts/test_capability_blocked_validate_timeout.py
python tests/llm/test_codex_agentic.py
python tests/fail_taxonomy/test_classify_fail.py
python scripts/probe_smoke.py --stage 3 --stage 5
```

N100 verification:

```text
.venv/bin/python scripts/validate_config.py \
  output/validate_timing/grounding_check_n100/candidate.json \
  --verbose-timing \
  --timing-dir output/validate_timing/grounding_check_n100
```

Observed result:

```text
ok=false
check=probe_grounding_list_wait_selector
total_ms≈57ms
spans=[validate_build_adapter]
```

The important part is that no `playwright_launch`, `goto_dom`, `xhr_quiet_wait`,
or `selector_wait` span appears. The candidate failed before browser/network
work.

## Debugging Notes

When a future batch shows `probe_grounding_*`:

1. Inspect the candidate selector/API and the relevant `digest.json` evidence.
2. If the digest evidence is wrong or incomplete, fix probe/digest generation,
   not the guard.
3. If the agent ignored obvious evidence, adjust `prompts/register_agent_AGENTS.md`
   or `prompts/config_writer.system.txt`.
4. If the guard false-rejects a valid inferred config, add a focused test and
   loosen the fail-open condition rather than disabling the whole guard.
