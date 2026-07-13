# notice-watcher register agent

You are an automated configuration agent.

## GOAL

Produce a working notice-watcher config JSON. Parent re-validates and publishes.

## STRICT SCOPE — TMPDIR ONLY

You may read **only files in this directory** (your cwd, the tmpdir). Do NOT
read, list, or browse any path outside this tmpdir. No `<REPO>` paths, no
absolute paths, no `..`, no PowerShell `Get-ChildItem` of parent dirs.

All inputs you need are already staged here:
- `AGENTS.md` (this file)
- `digest.json` — probe result (HTML samples, list_candidates, recognizer hints)
- `slug.txt` — target slug (single line)
- `url.txt` — target URL (single line)
- `failure_packet.json` — optional previous api_loop_once failed candidate
  and validation feedback. Treat it as diagnostic evidence, not as a template.
- `examples/*.json` — 2 curated prior configs (closest matches)
- `examples/manifest.json` — why each example was picked
- `config_writer_rules.txt` — the full ruleset for config authoring
- `validate_config.py` — validator wrapper
- `fetch_page.py` — live page fetcher (budget-limited — see LIVE FETCH)
- `python_path.txt` — python interpreter path used by the parent process
- `run_validator.sh` / `run_validator.bat` — validator launcher using that python
- `run_fetch.sh` / `run_fetch.bat` — fetch launcher using that python

## WORKFLOW

1. Read `digest.json`, `slug.txt`, `url.txt` first.
2. Read `examples/manifest.json` to see which examples are relevant.
3. If `failure_packet.json` exists, read it to learn what already failed.
   You may reuse, patch, or discard that candidate completely.
   If its failure text is DNS/network/browser infrastructure
   (`ERR_NAME_NOT_RESOLVED`, `Temporary failure in name resolution`,
   `TargetClosedError`, `browser launch failed`, Chromium sandbox/launch),
   that is NOT evidence that the selector or strategy was wrong. Do not switch
   away from a probe-grounded `playwright_html`/`httpx_html` direction solely
   because of such an infra failure.
4. Read 1-2 most relevant `examples/*.json`. Optionally skim
   `config_writer_rules.txt` only if uncertain about a field.
5. If digest evidence is contradictory or the article sample looks like the
   wrong page, use LIVE FETCH (below) — at most 1-2 fetches before your first
   candidate.
6. Before writing a config, perform SELF-VETO below. If it applies, STOP and
   emit final JSON with `ok:false` and the matching `stop_reason`.
7. Write your candidate to `./candidate.json` (this tmpdir).
8. Run validator using the staged launcher:
       ./run_validator.sh ./candidate.json     # Linux
       .\run_validator.bat ./candidate.json    # Windows
   Read JSON result.
9. If `ok=true` → STOP, emit final.
10. If failed: edit candidate.json once, re-run validator.
11. After **2 validate attempts** (1 initial + 1 retry): STOP regardless.
   Emit final with the last attempt and `stop_reason: max_cycles`.

## SELF-VETO (no config for non-board pages)

Before config authoring, inspect digest evidence: `list_html`,
`list_candidates`, `first_article_url` / article sample, and repeating list
patterns. If the target is clearly not a board/listing, stop early:

- single-article / content page (one main article and 0-few repeated list rows):
  `ok=false`, `stop_reason="non_board"`
- 404 / not-found shell (title/h1 says missing, deleted, Page Not Found, etc.):
  `ok=false`, `stop_reason="non_existent"`
- login-required page (login form or login-required wording):
  `ok=false`, `stop_reason="login_required"`

catalog / package / product / mod-hub listing 도 반복 카드 ≥3 + 각 row → 상세 페이지 링크면 정상 config 를 작성한다. self-veto 금지. non_board 는 반복 row 0~소수 + 단일 본문인 경우만.

Do not invent selectors or a minimal fake config for these cases. If the page is
ambiguous but could be an index/board, continue with config authoring and
validator feedback.

## PROBE-GROUNDED SELECTION

- Prefer selectors and URLs that appear verbatim in `digest.json`
  (`list_candidates.html_repeating_patterns[].selector`, `sample_url`,
  `first_article_url`, `clicked_resolved_url`, validated API candidates).
- If `recommended_strategy` says httpx/S1.Hcap but `notes` or
  `escalation_hint` says static HTML is an empty shell or
  `strategy=playwright_html` is required, treat the empty-shell note as the
  stronger signal. Use rendered `list_candidates` selectors with
  `playwright_html` unless you can point to a real static JSON/list source.
- If `list_candidates.traffic_json_api_candidates` contains a candidate whose
  rows match the rendered latest list (same titles, dates, or article URLs),
  prefer `strategy="httpx_json"` over browser polling. `source_script_hints`
  is evidence for where the JSON URL comes from; do not invent URL templates
  beyond what the engine can express.
- If `article_sample.api_candidates` contains a candidate with
  `url_id_match=true`, `body_looks_html=true`, and `body_field_path`, use it
  for article fetch: replace the article id in that candidate URL with
  `{post_id}`, set `article.fetch_kind="json"`, and set
  `article.content=[{"from":"json","path":<body_field_path>}]`. Do this before
  falling back to HTML article selectors; a static or rendered article page can
  be only a shell while the JSON candidate is the real body.
- Do not invent class names such as `.list-item__text` or CMS JSON endpoints
  unless digest evidence shows them. If the row itself contains title/date text,
  extract from `:self` with regex instead of inventing child selectors.
- Do not use SVG/icon/decorative candidates as list rows. Selectors containing
  `svg`, `g`, `path`, `circle`, `rect`, `use`, `#Layer_*`, or `#Group_*`, or
  candidates with empty `first_text` and no `sample_url`, are not article rows
  even when their `child_count` is high. Prefer a candidate whose `sample_url`
  is an article URL and whose row text contains a title/date. If only nav,
  footer, menu, or SVG candidates exist, stop instead of inventing a fake config.
- Validator feedback named `probe_grounding_*` means the candidate contradicted
  concrete probe evidence before live crawling. Fix by choosing selectors/API
  URLs that match `digest.json` HTML or HAR/API candidates; do not retry the
  same made-up selector with longer Playwright waits.
- If a previous candidate used a probe-grounded rendered selector and failed
  with DNS/browser launch infra errors, keep that direction and fix only fields
  that validation proves wrong.
- If `playwright_html` validation repeatedly fails with
  `ERR_NAME_NOT_RESOLVED`, `Temporary failure in name resolution`, or
  `Name or service not known`, treat it as a possible stealth DNS race. Retry
  the same probe-grounded config once with top-level `disable_stealth: true`.
  Do not use `headless:false`.

## LIVE FETCH (budget-limited)

The digest snapshots can be stale or mis-picked (probe sometimes samples the
wrong "first article"). When — and only when — digest evidence contradicts
itself or the validator result, you may fetch a live page:

    ./run_fetch.sh <url>              # static (httpx, Chrome headers)  — Linux
    .\run_fetch.bat <url>             # Windows
    ./run_fetch.sh <url> --render     # rendered DOM (stealth playwright) — only
                                      # if digest says static HTML is an empty shell

Output: one JSON line with `path` → compressed HTML written to
`./fetched_<n>.html` in this tmpdir. Read it with `sed` slices, not whole-file
`cat`. The compression is the same one used for the digest snapshots, so
evidence stays comparable.

- Hard budget: **5 fetches per session**, script-enforced (the 6th call is
  refused with rc=3). Failed attempts also count.
- Each fetch spends your wall clock (static ~2-5s, `--render` ~5-15s). Prefer
  static; `--render` only on empty-shell evidence.
- NOT a first resort. Do not fetch before reading `digest.json`. Do not use it
  to "explore" the site. Legitimate triggers: `article_sample` looks like a
  list/menu page instead of an article; the validator says a selector matched
  nothing although digest HTML shows it; you need the real
  `first_article_url` page to pick `article.content` selectors; an API
  candidate's response shape must be confirmed before betting `httpx_json` on it.
- Selectors must still appear verbatim in fetched or digest HTML — fetching
  does not license invented selectors.

## TOKEN DISCIPLINE

- Don't `cat` the same file twice.
- Don't read all examples — pick 1-2 from manifest scores.
- Don't dump huge JSON to stdout for inspection — read into your reasoning
  silently.
- Aim for **≤ 4 tool calls total** when not fetching (read inputs / write
  candidate / validate / optional retry). Each live fetch adds 2 (run +
  sed-read). Never exceed **8 tool calls total**.

## FINAL OUTPUT — strict JSON

Your final agent message MUST be a single JSON object (no prose):

    {
      "ok": <bool>,
      "candidate_path": "./candidate.json",
      "config": {},
      "attempts": [
        {"i": 1, "validate_ok": false, "error": "<short>"},
        ...
      ],
      "stop_reason": "validate_pass" | "max_cycles" | "agent_gave_up" | "error"
                     | "non_board" | "non_existent" | "login_required"
    }

### config field rule (STRICT — no exceptions)

- `ok=true` → include `"candidate_path": "./candidate.json"` and `config: {}`.
  NEVER echo the full cfg in the final message.
- `ok=false` → `config` = empty `{}`. ALWAYS. No partial dump, no "informative"
  last_config, no debug payload.
  - Applies to ALL cases: `validate_pass`, `max_cycles`, `agent_gave_up`,
    `error`, `non_board`, `non_existent`, `login_required`.
  - Reason: parent reads `./candidate.json` directly for the attempted cfg.
    Echoing it inflates the final message past the model output budget and
    the response gets truncated mid-string — parent then can't parse attempts
    or `stop_reason` (`LLMParseError: Expecting ',' delimiter`).

### attempts field rule

- `attempts[].error` ≤ 80 chars (validator's hard failure name + short detail).
- ≤ 3 attempt entries total.
- No JSON dump of cfg inside `attempts`.

Total final JSON target: ≤ 500 chars. If you're over, you're echoing a cfg
where you shouldn't.

## HARD RULES

- TMPDIR ONLY. No repo paths. No directory traversal.
- WRITE ONLY to `./candidate.json` in this tmpdir (the staged tools write
  their own files — that is fine).
- Live network ONLY via `./run_fetch.sh` / `.\run_fetch.bat`. NO hand-rolled
  `python -c` requests/urllib, curl, wget, Invoke-WebRequest.
- Max 5 live fetches (script-enforced).
- NO git, gh, push, commit, hg, svn.
- Max 2 validate cycles.
- Output strictly JSON. No prose outside the final JSON.
- No `headless: false` in config (production = headless only — parent will reject).
- If unclear: emit `{"ok": false, "stop_reason": "agent_gave_up", "config": {}, "attempts": [...]}` and stop.
