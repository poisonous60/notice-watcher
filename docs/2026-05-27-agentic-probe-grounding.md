# Agentic Probe Evidence Grounding

Date: 2026-05-27

Related commit: `00f62e2 fix validator probe grounding`

## Summary

This change adds a validator-side guardrail for generated configs that are
validated with probe digest evidence.

The problem was not that a bad URL or bad selector is always slow. The slow path
appears when a generated `playwright_html` candidate opens a page successfully
and then waits for a selector that never appears. The old validator could spend
the internal 25s budget in Playwright waits and return only a generic timeout.

The new guard checks the generated candidate against probe evidence before live
network/browser validation. If the candidate contradicts complete probe HTML or
captured article API evidence, validation fails quickly with a specific
`probe_grounding_*` check. That feedback goes back into the agentic retry loop.

Probe/HAR extraction is responsible for discovering evidence: rendered HTML,
captured APIs, article candidates, clicked routes, and source-script hints.
`probe_grounding_*` only checks whether a generated config contradicts
already-captured evidence. It cannot discover missing APIs, repair incomplete
HAR capture, infer date-token rollover behavior, or replace probe improvements.

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

## Why This Should Not Break Existing Runtime Configs

Existing deployed configs are not blocked just because this guard exists.

The guard only runs when `validate_built_config` receives a digest. Runtime
polling and plain config loading do not pass probe digest evidence, so their
behavior is unchanged.

New automatic generation paths that pass a digest may fail fast, but only when
the candidate contradicts complete validator-side probe evidence. Manual
`validate_config.py` runs can also invoke the guard if the candidate sits beside
`validator_digest.json` or `digest.json`; that is intentional for reproducing
agentic validation locally.

The guard does not require selectors to be copied verbatim from probe
candidates. For example, an agent may still create a more specific selector such
as `article.card a[href*='/news/']`; it passes as long as that selector matches
the probe HTML.

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

## Probe vs Agentic Boundary

The most important boundary:

```text
probe/HAR/digest = evidence acquisition
agentic          = evidence selection and config expression
validator guard  = contradiction detection
```

The guard must not become a substitute for probe extraction. If a site is an
SPA, the first responsibility is still to capture rendered DOM, HAR traffic,
clicked article samples, and JSON/API candidates in probe artifacts. Agentic
should not be expected to discover data that the probe never observed. It can
choose among evidence, combine selectors, and express a config, but it should
not be the primary crawler for unknown SPA behavior.

Implementation consequence: `_add_probe_grounding_checks(...)` consumes only the
digest already passed to validation. If evidence is absent or unsafe, it fails
open rather than trying to probe the live site.

### What Probe Should Capture

For SPA-like sites, probe should try to produce at least one of these evidence
types:

| evidence | why it matters |
|---|---|
| Rendered `list_html` | Lets selectors be grounded against the actual post list DOM. |
| `traffic_json_api_candidates` | Lets agentic prefer `httpx_json` over browser polling when list data is already available as JSON. |
| `source_script_hints` | Explains where an observed JSON URL came from, for example a JS file constructing monthly URLs. |
| `article_sample.html` | Grounds article content selectors and separates real body containers from SPA shells. |
| `article_sample.api_candidates` | Lets article body fetch use JSON when static/rendered article HTML is only a shell. |
| `clicked_resolved_url` | Handles client-side routes where direct GET and list-click navigation differ. |

If these are missing, the next generic fix usually belongs in probe extraction,
not in the validator guard.

### What Agentic May Still Infer

Agentic does not have to copy probe candidates literally. Valid inferred work
includes:

- narrowing a broad row selector, for example from `article.card` to
  `article.card:has(time)`;
- adding an anchor constraint such as `a[href*='/news/']` when it matches the
  rendered HTML;
- choosing the best candidate among several JSON APIs by comparing titles,
  dates, or URLs to rendered rows;
- replacing a captured article ID in an API URL with `{post_id}` when the
  candidate URL clearly contains the sampled article identity;
- using `:self` / regex extraction when the row itself contains title/date text.

The validator guard allows these as long as the resulting selector/API still
matches concrete evidence.

### What Agentic Should Not Invent

These are the patterns the guard is meant to push back on:

- CSS classes that do not occur in complete probe HTML.
- Playwright `wait_selector` values that match 0 nodes in rendered evidence.
- CMS/API endpoints that are not in HAR/API candidates and are not explained by
  a source-script hint or existing engine rule.
- HTML article selectors when the probe already captured a better JSON article
  body API.
- Strategy changes caused only by transient infrastructure errors such as DNS,
  Chromium launch, or `TargetClosedError`.

## SPA Failure Decision Tree

When a future SPA-like site fails, use this order:

1. **`probe_grounding_*` fired.**
   First compare `candidate.json` with `validator_digest.json`. Do not start by
   re-litigating live site timing; the guard is saying the candidate contradicts
   the validator-side evidence.

2. **Digest evidence is correct and complete.**
   Fix the generated selector/API or the prompt rule that led the agent away
   from the evidence.

3. **Probe has rendered rows and/or JSON list evidence, but agentic ignored it.**
   Fix prompt/agentic input. The model should choose from existing evidence.

4. **Probe has evidence, agentic chose it, but validator says
   `probe_grounding_*`.**
   Inspect candidate vs digest. If the candidate is unsupported, let the retry
   fix it. If the digest is wrong or stale, fix probe/digest.

5. **Probe has no rendered rows and no list API, but the site visibly loads data
   after interaction.**
   Improve probe: scroll, click tab/category, wait for the right network phase,
   or capture the interaction that produces the list. Do not loosen the guard.

6. **HAR has the API response, but it is not promoted to
   `traffic_json_api_candidates` or `article_sample.api_candidates`.**
   Improve `probe.extract` / JSON row-shape detection. This was the GAMECITY
   class: URL identity (`link_url`) was the row identity even without a classic
   `id` field.

7. **The site exposes captured JSON matching rendered latest rows.**
   Prefer expressible `httpx_json` over browser polling. If the agent chooses
   Playwright anyway, fix prompt/agentic selection before adding waits.

8. **The site uses a URL shape the engine cannot express generically.**
   Do not hide it as a prompt trick. Add a generic engine surface only after
   seeing the pattern on multiple sites, or use a site-specific adapter/config
   with the limitation documented.

9. **The failure is DNS/browser/Chromium infrastructure.**
   Do not change strategy solely from that error. Keep the probe-grounded
   direction and fix the infrastructure or retry with preserved logs.

10. **The site is blocked, login-only, or requires tokens that probe cannot
   obtain.**
   End as capability-blocked/policy/url-dead according to the existing
   workflow. Agentic should not invent configs for missing evidence.

## Evidence Tiers

Use this language when deciding whether the guard may hard-fail:

| tier | examples | validator guard posture |
|---|---|---|
| Complete positive evidence | Rendered HTML/HAR candidate with full sample and matching selector/API. | Candidate may pass grounding. |
| Complete negative evidence | Full rendered HTML exists and selector matches 0 nodes. | Candidate may hard-fail. |
| Incomplete evidence | Truncated HTML, prompt-compressed HTML, static fallback for Playwright, no API candidates. | Fail open. Do not use as negative evidence. |
| Contradictory evidence | Static says shell, rendered/HAR has rows; or direct GET differs from clicked route. | Prefer concrete rendered/HAR/click evidence and document the contradiction. |

This is why the implementation stages both files in agentic workdirs:

- `digest.json`: compressed for the child model to read cheaply.
- `validator_digest.json`: full digest for validator grounding checks.

The child model should see enough evidence to reason. The validator should use
complete evidence when deciding whether a candidate contradicts reality.

## Known Caveats

False-positive risks:

- Probe captured a non-representative rendered state, A/B variant,
  cookie/language state, or transient shell.
- A selector is valid only after an interaction or lazy-load step that probe did
  not capture.
- A JSON endpoint is in the same semantic family, but the current URL-family
  matcher is too strict for non-numeric or date-token changes.
- Article content is intentionally empty, but the generated config forgot
  `article.body_empty_acceptable=true`.

False-negative risks:

- Missing, truncated, malformed, or prompt-compressed evidence fails open.
- Empty `article_sample.api_candidates` is treated as unknown, not rejection.
- Static HTML can pass grounding while runtime SPA behavior is still wrong.
- URL-family matching can accept a structurally similar endpoint that is
  semantically stale.

If the guard rejects a genuinely valid inferred config, add a focused regression
test and loosen that specific fail-open condition. Do not disable the entire
guard.

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
