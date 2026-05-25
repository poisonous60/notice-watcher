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
- `python_path.txt` — python interpreter path used by the parent process
- `run_validator.sh` / `run_validator.bat` — validator launcher using that python

## WORKFLOW

1. Read `digest.json`, `slug.txt`, `url.txt` first.
2. Read `examples/manifest.json` to see which examples are relevant.
3. If `failure_packet.json` exists, read it to learn what already failed.
   You may reuse, patch, or discard that candidate completely.
4. Read 1-2 most relevant `examples/*.json`. Optionally skim
   `config_writer_rules.txt` only if uncertain about a field.
5. Before writing a config, perform SELF-VETO below. If it applies, STOP and
   emit final JSON with `ok:false` and the matching `stop_reason`.
6. Write your candidate to `./candidate.json` (this tmpdir).
7. Run validator using the staged launcher:
       ./run_validator.sh ./candidate.json     # Linux
       .\run_validator.bat ./candidate.json    # Windows
   Read JSON result.
8. If `ok=true` → STOP, emit final.
9. If failed: edit candidate.json once, re-run validator.
10. After **2 validate attempts** (1 initial + 1 retry): STOP regardless.
   Emit final with the last attempt and `stop_reason: max_cycles`.

## SELF-VETO (no config for non-board pages)

Before config authoring, inspect digest evidence: `list_html`,
`list_candidates`, `first_article_url` / article sample, and repeating list
patterns. If the target is clearly not a board/listing, stop early:

- single-article / content page (one main article and 0-few repeated list rows):
  `ok=false`, `stop_reason="non_board"`
- catalog/package/product listing that is not a latest-notice/post board:
  `ok=false`, `stop_reason="non_board"`
- 404 / not-found shell (title/h1 says missing, deleted, Page Not Found, etc.):
  `ok=false`, `stop_reason="non_existent"`
- login-required page (login form or login-required wording):
  `ok=false`, `stop_reason="login_required"`

Do not invent selectors or a minimal fake config for these cases. If the page is
ambiguous but could be an index/board, continue with config authoring and
validator feedback.

## TOKEN DISCIPLINE

- Don't `cat` the same file twice.
- Don't read all examples — pick 1-2 from manifest scores.
- Don't dump huge JSON to stdout for inspection — read into your reasoning
  silently.
- Aim for **≤ 4 tool calls total** (read inputs / write candidate / validate /
  optional retry).

## FINAL OUTPUT — strict JSON

Your final agent message MUST be a single JSON object (no prose):

    {
      "ok": <bool>,
      "config": <object>,
      "attempts": [
        {"i": 1, "validate_ok": false, "error": "<short>"},
        ...
      ],
      "stop_reason": "validate_pass" | "max_cycles" | "agent_gave_up" | "error"
                     | "non_board" | "non_existent" | "login_required"
    }

### config field rule (STRICT — no exceptions)

- `ok=true` → `config` = the passing cfg dict (full).
- `ok=false` → `config` = empty `{}`. ALWAYS. No partial dump, no "informative"
  last_config, no debug payload.
  - Applies to ALL ok=false cases: `max_cycles`, `agent_gave_up`, `error`,
    `non_board`, `non_existent`, `login_required`.
  - Reason: parent reads `./candidate.json` directly for the last attempted
    cfg. You do NOT need to echo it in the final JSON. Echoing it inflates
    the final message past the model output budget and the response gets
    truncated mid-string — parent then can't parse anything at all
    (`LLMParseError: Expecting ',' delimiter`).

### attempts field rule

- `attempts[].error` ≤ 80 chars (validator's hard failure name + short detail).
- ≤ 3 attempt entries total.
- No JSON dump of cfg inside `attempts`.

### headers field rule (when ok=true)

In your candidate.json `headers` dict, write **MINIMAL** keys only:
- `User-Agent` — one line
- `Accept` — one line (e.g. `text/html,...` for HTML or `application/rss+xml,...` for RSS)

Do NOT echo every header the digest captured. Specifically avoid:
- `Accept-Language`, `Referer`, `Upgrade-Insecure-Requests`
- `sec-ch-ua*`, `sec-fetch-*`, `sec-ch-platform`, ...
- `cache-control`, `pragma`, `connection`, ...

The engine fills the rest from defaults. Long header blobs are the main cause
of final-message truncation (see "config field rule" reason above).

Total final JSON target: ≤ 500 chars. If you're over, you're echoing a cfg
where you shouldn't.

## HARD RULES

- TMPDIR ONLY. No repo paths. No directory traversal.
- WRITE ONLY to `./candidate.json` in this tmpdir.
- NO git, gh, push, commit, hg, svn.
- Max 2 validate cycles.
- Output strictly JSON. No prose outside the final JSON.
- No `headless: false` in config (production = headless only — parent will reject).
- If unclear: emit `{"ok": false, "stop_reason": "agent_gave_up", "config": {}, "attempts": [...]}` and stop.
