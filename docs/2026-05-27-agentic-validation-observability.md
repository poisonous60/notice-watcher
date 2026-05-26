# 2026-05-27 Agentic Validation Observability Note

## Why This Exists

The `2026-05-24-games-jp` batch showed many `validation_timeout` labels, but the
first patch was mostly hypothesis-driven. This session changed the workflow to
measure the actual production path before changing behavior.

The important lesson: the visible `validation_timeout` label was not one root
cause. Preserved N100 logs showed several different layers:

- validator subprocess timing was sometimes unavailable, so old failures looked
  like site slowness;
- Codex agentic validator runs initially had sandbox DNS/browser-launch failures
  on N100;
- after network was fixed, agentic sometimes changed strategy because retry
  feedback treated infra errors like bad selectors;
- for GAMECITY, probe eventually surfaced the right JSON APIs, but agentic first
  used the JSON list while missing the captured JSON article-body API.

This document records what changed and which files now measure agentic behavior.

## Commits In This Session

| commit | purpose |
|---|---|
| `22ea9a9` | preserve validator timing artifacts from agentic validation |
| `7a97ae2` | pass the timing directory into agent validator launches |
| `9bb9648` | preserve agentic run logs and optional workdir snapshots |
| `3443f04` | let N100 agentic validator runs use network/browser access |
| `aacc4dd` | keep probe-grounded strategy after infra failures |
| `de48426` | remove empty-shell vs `S1.Hcap` strategy contradiction and retry transient Playwright DNS |
| `c0f3b95` | surface URL-identified JSON lists and JS source hints |
| `6ad801f` | put captured body-API priority into agentic tmpdir instructions |
| `9bfb826` | record the GAMECITY production registration result |

## Measurement Hooks Added

### `scripts/validate_config.py`

Added a gated timing mode:

- CLI: `--verbose-timing`
- env: `VALIDATE_TIMING=1`
- optional output override: `--timing-dir` or `VALIDATE_TIMING_DIR`
- strategy comparison: `--strategy=httpx_html|playwright_html|auto`

When enabled, stdout remains the validator result JSON. Timing is written to
JSON files under `output/validate_timing/` or the supplied timing directory.
That keeps agent JSON parsing intact.

Artifact shape:

```json
{
  "slug": "www_gamecity_ne_jp_news",
  "candidate_path": "candidate.json",
  "strategy": "httpx_json",
  "status": "ok",
  "error": null,
  "total_ms": 409.6,
  "trace_id": "...",
  "spans": [
    {"name": "validate_build_adapter", "duration_ms": 39.3, "ok": true},
    {"name": "validate_fetch_list", "duration_ms": 224.1, "ok": true},
    {"name": "validate_fetch_article", "duration_ms": 83.6, "ok": true}
  ]
}
```

This answers whether time is going into adapter build, list fetch, article fetch,
or a validator timeout.

### `generate/codex_agentic.py`

Added agentic run preservation when `VALIDATE_TIMING=1`.

Files written to `output/validate_timing/`:

- `agentic_run__<slug>__<ts>__pid<PID>__<rand>.json`
  - records workdir path, digest path, optional `failure_packet.json`,
    Codex args, selected env, stdout/stderr tails, parsed `last.json`,
    attempted `candidate.json`, workdir file listing, and cleanup state.
- `agentic_attempt__<candidate>__<ts>__pid<PID>__ppid<PPID>.json`
  - written by the staged `run_validator.sh` / `.bat` wrapper around each
    validator invocation inside the agent tmpdir.
  - records `argv`, cwd, repo root, timing dir, start/end status, rc, and
    elapsed time.

Optional env:

- `VALIDATE_TIMING_PRESERVE_WORKDIR=1`
  - copies the whole agent tmpdir to
    `output/validate_timing/agentic_workdirs/<slug>__<ts>__pid<PID>__<rand>/`.
  - preserves `digest.json`, `failure_packet.json`, `candidate.json`,
    `last.json`, `codex_stdout.jsonl`, `codex_stderr.txt`,
    `codex_user_prompt.txt`, `run_validator.sh`, and local timing files.

The wrapper also sets `VALIDATE_TIMING_DIR=<workdir>/validate_timing` for the
agent validator process, so the validator timing JSON and the agentic attempt
JSON land in the same tmpdir and can be copied out.

### Agentic Network Mode

`generate/codex_agentic.py` now launches Codex agentic with sandbox bypass for
this networked validator task. N100 evidence showed the previous sandbox caused
DNS and Chromium launch failures inside the agent, which looked like site
failures. The parent still audits the repo before and after the agent run; the
agent may only publish through `candidate.json` and parent re-validation.

### Agentic Input Fixes

`prompts/register_agent_AGENTS.md` now explicitly tells the tmpdir agent:

- infra failures such as `ERR_NAME_NOT_RESOLVED`, browser launch errors, and
  `TargetClosedError` are not evidence that a probe-grounded selector or
  strategy was wrong;
- if static HTML is an empty shell, that signal beats stale `S1.Hcap` static
  success;
- if `list_candidates.traffic_json_api_candidates` matches rendered latest rows,
  prefer `httpx_json` over browser polling;
- if `article_sample.api_candidates` has `url_id_match=true`,
  `body_looks_html=true`, and `body_field_path`, use it for
  `article.fetch_kind="json"` before falling back to HTML selectors.

`tests/llm/test_codex_agentic.py` locks that these rules are actually staged in
the agent tmpdir `AGENTS.md`, including the evidence guards
`url_id_match`, `body_looks_html`, and `body_field_path`.

## Probe Evidence Added For Agent Decisions

`probe/hydration.py`:

- JSON list rows can now be recognized by `title/name + url/link/href/path`,
  not only `title/name + id/no/slug`.
- This is needed for APIs where the article URL is the stable row identity.

`probe/extract.py`:

- `traffic_json_api_candidates` now includes `source_script_hints`.
- The hint finds same-site JavaScript responses that appear to construct the
  observed JSON URL, either by exact file name or by stable prefix/suffix around
  a numeric token.
- This is diagnostic evidence for the agent, not a new engine URL-template
  feature.

`scripts/register.py`:

- when static HTML is a shell but HAR contains JSON API candidates, the
  escalation hint tells the agent to compare those candidates against rendered
  latest rows and verify where the URL is generated.
- it also tells the agent to stop instead of inventing an engine config if the
  generation/fallback rule cannot be expressed.

## How To Reproduce The Measurement

Enable timing on N100:

```bash
systemctl --user set-environment VALIDATE_TIMING=1 VALIDATE_TIMING_PRESERVE_WORKDIR=1
systemctl --user restart notice-bot.service
```

Run a production-path retry from the dev box:

```bash
python scripts/remote.py batch-register --url "https://www.gamecity.ne.jp/news/" --force
python scripts/remote.py jobs --min-id <job_id> --wait --interval 20 --max-wait 900
```

Inspect N100 artifacts:

```bash
ssh $DEPLOY_HOST 'cd ~/notice-watcher && find output/validate_timing -maxdepth 2 -type f -name "*gamecity*" | sort'
ssh $DEPLOY_HOST 'cd ~/notice-watcher && find output/validate_timing/agentic_workdirs -maxdepth 2 -type f -path "*gamecity*" | sort'
```

Useful files:

- `agentic_run__...json`: what Codex was given, what it emitted, and what files
  existed in the tmpdir.
- `agentic_workdirs/.../candidate.json`: the actual candidate the agent wrote.
- `agentic_workdirs/.../last.json`: the final JSON the agent returned.
- `agentic_workdirs/.../failure_packet.json`: previous API-loop failure passed
  to agentic.
- `agentic_workdirs/.../validate_timing/*.json`: validator attempts run by the
  agent.
- `output/probe/<slug>/list_candidates.json`: list JSON candidates and
  `source_script_hints`.
- `output/probe/<slug>/article_candidates.json`: captured article-body API
  candidates.

Disable measurement after the investigation:

```bash
systemctl --user unset-environment VALIDATE_TIMING VALIDATE_TIMING_PRESERVE_WORKDIR KEEP_AGENT_WORKDIR
systemctl --user restart notice-bot.service
```

## What The Measurements Showed

For GAMECITY:

1. Before preserving workdirs, the agentic candidate and validator inputs were
   lost after cleanup.
2. After preservation, N100 logs showed Codex validator DNS/browser failures,
   not slow site navigation.
3. After network bypass, GAMECITY still failed because probe diagnosis gave a
   contradictory static hint and the agent switched to `httpx_html`.
4. After empty-shell strategy cleanup, probe exposed rendered rows, but
   Playwright DNS could still fail fast.
5. After JSON URL identity detection, `traffic_json_api_candidates` surfaced
   the monthly list JSON and `source_script_hints` pointed to `/js/news.js`.
6. The next failure was no longer timeout: agentic chose the JSON list but
   ignored the captured article JSON body API.
7. After putting the article API rule directly in tmpdir `AGENTS.md`, N100 job
   `#3623` registered successfully through the normal worker path.

For the failed-batch retry after `c0f3b95`:

| group | evidence |
|---|---|
| actual entry/baseline blocked | BandaiNamco, Cygames root/news, Level5, Aktsk root/news |
| transient N100 Chromium DNS | KoeiTecmo news, Hoyoverse news |
| non-board reject | Hoyoverse root |
| agentic selection fixed by this session | GAMECITY news |

So the batch symptom was not one validator timeout bug. It was a mix of missing
observability, agent sandbox infra, probe strategy contradiction, JSON candidate
blind spots, and true blocked sites.

## Remaining Caveat

GAMECITY registered with a list URL observed in HAR:

```text
https://www.gamecity.ne.jp/cms-data/json/news_202605.json
```

`/js/news.js` proves the site computes current `YYYYMM` and falls back to older
months. This session deliberately did not add a generic date-token/fallback URL
engine from one site. The current generated config works now, but month rollover
needs either another same-pattern case to justify a generic engine surface or a
site-specific handwritten adapter.
