---
slug: infra_validator_timeout_fix
url: internal://validator-timeout
status: "🛠️ validator timeout root-cause + surgical fix design"
outcome: improved
date: 2026-05-26
fix_layer: C+D
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

## 2026-05-26 v2 — measured follow-up

The first patch above was not enough: it answered the work-budget hypothesis but did not prove whether the batch was burning time in site navigation, selector waits, browser launch, or stale classification.

Changes made for measurement:

- `scripts/validate_config.py --verbose-timing` / `VALIDATE_TIMING=1` writes JSON timing artifacts under `output/validate_timing/` while preserving stdout as the validator result JSON.
- `--strategy=httpx_html|playwright_html|auto` lets the same candidate be compared under both HTML strategies.
- `engine/strategies/playwright_html.py` now emits spans for `playwright_launch`, `goto_dom`, `cf_wait`, `xhr_quiet_wait`, `selector_wait`, and `page_content`.
- `engine/strategies/httpx_html.py` now emits spans for `httpx_get`, `parse_list_html`, and `parse_article_html`.

Measured evidence:

| scope | result |
|---|---|
| Dev-box minimal 5-site comparison | `httpx_html` candidates finished in ~0.3-0.6s except Capcom 403; Playwright candidates finished in ~1.2-11.8s. Dominant Playwright cost was launch + `xhr_quiet_wait`; CF wait was ~0ms and no 15s nav hang reproduced. |
| Actual `2026-05-24-games-jp` batch rows | N100 DB snapshot covered 100 catalog entries and 146 job rows. 19 unique entries had a `validate_timeout` token somewhere in their history; the latest state had 8 `gen_fail/validate_timeout` rows. Dev-box reruns of the latest timeout rows did not reproduce 25s validator burn: observed validator artifacts for the same URLs were ~0.3-5.4s. Several reruns registered successfully (`capcom-games.com/news`, `drecom.co.jp/news`, `hoyoverse.com/news`, earlier `shadowverse.jp/news`). |
| Failure label check | Some dashboard rows were stale/misleading: `bot.fail_taxonomy._validate_timeout` matched any `validate_internal_timeout_*` token anywhere in agentic history, even when the last attempt failed for a different reason. |

Scenario mapping from measured reruns:

| slug/name | measured validator cost | dominant phase | scenario |
|---|---:|---|---|
| capcom-games.com/news | 0.3-2.1s | `httpx_get` on first run, then tiny | Not B/C; recovered with `httpx_html`. |
| gamecity.ne.jp/news | 2.9-5.4s | Playwright `goto_dom` + `xhr_quiet_wait` | Not timeout now; generated selector/path still yields `posts_nonempty`. |
| umamusume.jp/news | 0.3-1.7s after schema failure | `httpx_get` | Not timeout now; agentic max_cycles / bad candidates. |
| falcom.co.jp | no validator burn; gate/classifier rejected root | WordPress marker false start then content reject | Not validator timeout. |
| hoyoverse.com | 2.5-2.9s | Playwright `xhr_quiet_wait`; also `run_validator.sh` command mistake in one agent attempt | Not nav hang; agentic candidate/tool-use issue. |
| hoyoverse.com/news | 0.5s when `httpx_json`, 3.6-5.2s when Playwright | `xhr_quiet_wait` if Playwright | Recovered; JSON API is the right path. |
| drecom.co.jp/news | registered on dev rerun | no wrapper timing because it passed through direct api-loop validation | Recovered; not evidence for timeout. |

Fix decision:

- Do **not** apply global `wait_until="commit"`, Chromium reuse, CF cache changes, or a hard strategy override. The measured data did not show CF wait, browser launch, or navigation timeout as the current dominant root cause across the batch.
- Apply a narrow taxonomy fix: when agentic attempts are serialized as JSON, classify `validate_timeout` only if the **last** attempt error is `validate_internal_timeout_*`. A stale timeout from an earlier attempt no longer hides the current failure reason.
- Keep the new timing instrumentation so the same failed-batch retry can produce N100-side timing JSON after deployment.

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

## 2026-05-26 v3 — actual agentic log root cause

After deploying agentic workdir preservation and rerunning the actual
`2026-05-24-games-jp` URLs on N100, the preserved logs changed the diagnosis:

| slug | actual log evidence | root cause | fix surface |
|---|---|---|---|
| `capcom-games.com/news` | Before sandbox fix, validator failed with DNS inside Codex sandbox. After `3443f04`, the actual URL registered. | Agentic sandbox network, not site slowness. | `generate/codex_agentic.py` sandbox mode. |
| `falcom.co.jp` | Before sandbox fix, same DNS/timeout class. After `3443f04`, the actual URL registered. | Agentic sandbox network, plus article body quality handled by agentic. | sandbox mode + preserved logs. |
| `gamecity.ne.jp/news` | Probe Playwright loaded rows, but diagnosis said both `S1.Hcap` httpx and `정적 응답이 빈 shell / playwright_html 필수`. api-loop Playwright then hit fast `ERR_NAME_NOT_RESOLVED`; agentic switched to `httpx_html` and got 0 rows. | Agentic selection was misled by contradictory probe strategy plus transient Playwright DNS. The rendered selector was correct. | probe diagnosis, agent prompt, Playwright transient retry. |

The failure is therefore not a single validator timeout bug. The actual batch
had three layers:

1. missing logs: agentic tmpdirs were deleted, hiding the candidate and validator inputs;
2. sandbox infra: Codex `workspace-write` broke validator DNS/browser launch on N100;
3. selection: once infra was fixed, GAMECITY still got a contradictory probe hint and agentic fell back to static HTTP for a rendered-only list.

Additional surgical fixes:

- `probe/diagnose.py` now treats `S1.Hcap` as a static-like response during
  static-vs-headless comparison. If the best static-like response is still an
  empty shell, `S1.Hcap` cannot win `recommended_strategy` or verdict.
- `prompts/config_writer.system.txt` and `prompts/register_agent_AGENTS.md`
  make the empty-shell / `playwright_html 필수` note stronger than a stale
  `recommended_strategy=httpx/S1.Hcap` hint.
- `engine/strategies/playwright_html.py` retries `page.goto` once for fast
  transient DNS navigation errors only. It does not extend timeouts, does not
  switch to `wait_until="commit"`, and does not change default strategy.

This keeps Q1's constraint: probe verdict does not hard-force strategy. It only
removes a contradiction and lets the agent choose from consistent evidence.

## 2026-05-27 v4 — GAMECITY stable path

N100 job `#3611` confirmed the v3 probe contradiction fix worked: GAMECITY now
reports `JS 실행 필요` with Playwright as the recommended entry. It still failed
because both Playwright `goto_dom` attempts hit fast `ERR_NAME_NOT_RESOLVED`, and
agentic left an invalid `candidate.json`.

The actual stable path is not more Playwright waiting. HAR showed the page loads
`/js/news.js`, which constructs monthly list JSON URLs:

- `/cms-data/json/news_202605.json`
- `/cms-data/json/news_202604.json`
- `/cms-data/json/news_202603.json`

Those responses were absent from `traffic_json_api_candidates` because
`find_list_in_json` required an explicit id-like key. GAMECITY list rows use
`name + link_url + date`; `link_url` is the post identity. The safe generic fix
is to accept URL identity keys for JSON row-shape detection. A broader
date-token/fallback URL engine surface is deferred until at least one more
same-pattern site appears in the batch.

Measured validation of the stable config path:

| config path | result |
|---|---|
| `httpx_json` list `https://www.gamecity.ne.jp/cms-data/json/news_202605.json`, article `https://www.gamecity.ne.jp/cms-data/json/news/{post_id}.json` | PASS on dev box: 15 posts, first article body 10326 chars |

This explains why “SPA handling already existed” was not enough: the existing
SPA path could render rows, but the JSON-list recognizer did not understand rows
whose identity is a URL field rather than an id field. When N100 Playwright DNS
flaked, there was no non-browser fallback candidate for the agent to choose.
The month rollover behavior is proven by `/js/news.js`, not HAR alone: the
script computes the current `YYYYMM`, fetches `news_YYYYMM.json`, and falls back
to older months on error. A hard-coded monthly URL is therefore a site-specific
temporary config, not a robust generic engine solution.

N100 job `#3613` then confirmed the JSON list signal itself was fixed: the
monthly list JSON candidates appeared at the top of `traffic_json_api_candidates`
with `source_script_hints`. The next failure was different and faster: agentic
picked the JSON list but ignored the already captured body JSON candidate
(`/cms-data/json/news/{post_id}.json`) and tried the HTML article page, producing
`article_body_len` / JSON decode failures instead of timeout. The generic follow-up
is to put the JSON list/body handoff rules directly into the agentic tmpdir
`AGENTS.md`, not only the larger `config_writer_rules.txt`.

After that D-layer handoff fix, N100 job `#3623` registered GAMECITY through the
normal worker path. The generated config correctly uses `httpx_json` for both the
list and article body APIs. Remaining caveat: its list URL is the observed
current-month `news_202605.json`; this is operationally valid now but not a
general date/fallback engine solution.

## 2026-05-27 v5 — probe evidence grounding guardrail

The next failure mode was not that a wrong selector or URL is inherently slow.
It is slow only when the wrong candidate is validated through Playwright:
`page.goto` may succeed, then `wait_selector` is allowed to miss and still burn
`idle_timeout_ms` before extraction returns 0 rows/body. A missing URL usually
fails quickly with DNS/HTTP/navigation errors; a selector/list mismatch can burn
inside an otherwise loaded page.

Generic fix applied:

- `generate.validate.validate_built_config` now runs a pre-network
  `probe_grounding_*` guard after adapter construction and before
  `fetch_list`. It fails fast when a generated candidate contradicts concrete
  probe evidence:
  - HTML row/list wait selectors match 0 nodes in complete `list_html`.
  - Playwright article wait selector matches 0 nodes in complete
    `article_sample.html`.
  - HTML article content selectors all match 0 nodes in complete
    `article_sample.html`.
  - JSON article `url_template` is outside captured useful
    `article_sample.api_candidates`.
- The guard is evidence-based, not an allowlist. Synthesized selectors are
  allowed when they actually match probe HTML.
- Missing, truncated, or prompt-compressed HTML is treated as unknown and fails
  open. This avoids rejecting legitimate configs from incomplete probe samples.
- Agentic workdirs now keep compressed `digest.json` for the model and a full
  `validator_digest.json` for `validate_config.py`, so child validation can use
  full evidence without asking the small agent to read the large file.
- `prompts/register_agent_AGENTS.md` documents `probe_grounding_*` feedback so
  the retry loop fixes the selector/API choice instead of increasing waits.

This improves agentic config generation **indirectly**: it does not add new
site evidence or make the model intrinsically smarter, but it turns vague
25-second validation failures into specific, cheap feedback that points the
agent back to probe-grounded selectors and APIs.
