# notice-watcher register agent

You are an automated configuration agent for notice-watcher.

## GOAL

Produce a working notice-watcher config JSON for the target site. The parent
process will validate your output independently and atomically publish if it
passes.

## YOUR WORKDIR

Files in this directory (the codex `-C` working dir):
- `AGENTS.md` — this file (read it first)
- `digest.json` — probe result: HTML samples, list_candidates, recognizer hints
- `slug.txt` — target slug (single line)
- `url.txt` — target URL (single line)
- `examples/` — curated prior configs (3-5) chosen by parent as closest matches
- `examples/manifest.json` — `{slug, score, reason}` for each example
- `validate_config.py` — validator wrapper (run via `python`)

## REPO ACCESS

The repository root is at the path in `repo_path.txt`. You MAY read any file
there for prior-art context. Useful starting points:
- `configs/*.json` — other successful configs
- `engine/recognizers/*.py` — recognizer URL patterns
- `prompts/config_writer*.txt` — the original generation prompt
- `output/probe/<slug>/` — probe artifacts for this slug
- `docs/config 기반 엔진 가이드.md` — config engine documentation

## WORKFLOW

1. Read `digest.json`, `slug.txt`, `url.txt`.
2. Inspect `examples/` for the closest-matching pattern.
3. If blocked, read related code/configs in the repo for grounding.
4. Write your candidate to `./candidate.json` (in this workdir).
5. Run the validator:
       python ./validate_config.py ./candidate.json
   Read the JSON result on stdout.
6. If `ok=true` → STOP. Emit final JSON.
7. If failed: edit `candidate.json` once, re-run validator.
8. After **3 validate cycles total** (1 initial + 2 retries): STOP regardless.
   Emit final with the last attempt and `stop_reason: max_cycles`.

## FINAL OUTPUT — strict JSON

Your final agent message MUST be JSON matching the schema, with no prose:

    {
      "ok": <bool>,
      "config": <object — the candidate>,
      "attempts": [
        {"i": 1, "validate_ok": false, "error": "<short reason>"},
        ...
      ],
      "stop_reason": "validate_pass" | "max_cycles" | "agent_gave_up" | "error"
    }

If `ok=true` then `config` MUST be present.

## HARD RULES (also restated in user prompt — they MUST agree)

- **WRITE ONLY to this workdir.** Do NOT create or modify any file under the
  repository path. Even if your sandbox permits the write, the parent will
  detect it via a mtime+size audit and reject the registration.
- **NO git commands.** No `git`, `gh`, `hg`, `svn`, no push, no commit.
- **NO modifications to** `engine/`, `prompts/`, `scripts/`, `bot/`,
  `dashboard/`, `tests/`, `docs/`, `output/poll_state/`.
- **Max 3 validate cycles.** Do not retry past that. Emit and stop.
- **Output strictly per the JSON schema.** NO prose outside the final JSON.
- **No `headless: false`** in your config — N100 (production) runs headless
  only. The parent validator will reject `headless: false`.
- If unclear how to proceed: emit
       {"ok": false, "stop_reason": "agent_gave_up", "config": {...best...}, "attempts": [...]}
  with whatever partial work you have, and stop.
