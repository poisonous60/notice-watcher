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
- `examples/*.json` — 2 curated prior configs (closest matches)
- `examples/manifest.json` — why each example was picked
- `config_writer_rules.txt` — the full ruleset for config authoring
- `validate_config.py` — validator wrapper (run via `python`)

## WORKFLOW

1. Read `digest.json`, `slug.txt`, `url.txt` first.
2. Read `examples/manifest.json` to see which examples are relevant.
3. Read 1-2 most relevant `examples/*.json`. Optionally skim
   `config_writer_rules.txt` only if uncertain about a field.
4. Write your candidate to `./candidate.json` (this tmpdir).
5. Run validator:
       python ./validate_config.py ./candidate.json
   Read JSON result.
6. If `ok=true` → STOP, emit final.
7. If failed: edit candidate.json once, re-run validator.
8. After **2 validate attempts** (1 initial + 1 retry): STOP regardless.
   Emit final with the last attempt and `stop_reason: max_cycles`.

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
    }

`config` MUST be present (empty `{}` if you give up).

## HARD RULES

- TMPDIR ONLY. No repo paths. No directory traversal.
- WRITE ONLY to `./candidate.json` in this tmpdir.
- NO git, gh, push, commit, hg, svn.
- Max 2 validate cycles.
- Output strictly JSON. No prose outside the final JSON.
- No `headless: false` in config (production = headless only — parent will reject).
- If unclear: emit `{"ok": false, "stop_reason": "agent_gave_up", "config": {}, "attempts": [...]}` and stop.
