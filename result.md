# Chunk A Result

## Root Cause

- `probe.signals.classify` treated all 403/429/503 as bot-block evidence before checking soft-not-found bodies. S3/CloudFront missing objects and themed HTML 404 pages were therefore surfaced as `BLOCKED_BOT` and later `ENTRY_BLOCKED`.
- `probe.diagnose.diagnose` let the static-vs-headless size rule erase S1 OK evidence even when probe already had strong row candidates, causing `Playwright headless + stealth (S4)` to be recommended for another-eden.

## Changes

- `probe/signals.py`: added 403 soft-not-found detection for S3 AccessDenied XML, repeated HTML 404 markers, and empty-ish 403 bodies. Challenge markers still win and remain `BLOCKED_BOT`.
- `probe/diagnose.py`: added a strong static-row guard: S1 OK + `html_repeating_patterns` row candidate `child_count >= 10` + `sample_url` suppresses the Playwright size override.
- Tests:
  - `tests/probe_heuristics/test_signals_classify.py`
  - `tests/probe_heuristics/test_diagnose_static_rows_prefer_httpx.py`
- Case file:
  - `docs/cases/_generic_probe_verdict_soft404_and_static_rows.md`

## Replay Evidence

Artifacts were pulled read-only from N100 for the four requested slugs. No N100 code, git, or service action was performed.

```text
heaven-burns-red: ENTRY_BLOCKED -> TARGET_NOT_FOUND
shadowverse-wb: ENTRY_BLOCKED -> TARGET_NOT_FOUND
shinycolors: ENTRY_BLOCKED -> TARGET_NOT_FOUND
another-eden: JS 실행 필요 / Playwright S4 -> 정적 HTTP로 충분 / httpx (S1.H2)
```

## Verification

- `python scripts/probe_smoke.py --stage 5`: PASS, 1374 cases, 0 FAIL, 1 existing WARN.
- `python scripts/probe_smoke.py --stage 3 --stage 5`: PASS, 1650 PASS, 0 FAIL, 1 existing WARN.
- `python scripts/probe_smoke.py`: PASS, 1660 PASS, 0 FAIL, 1 existing WARN.
- `python scripts/vocab_lint.py`: FAIL, 6 pre-existing avoid-term hits in `.claude/skills/hand-config/SKILL.md` and older `docs/cases/*`; no hits in changed files.

## Escalate / Notes

- The initial read-only tar stream through PowerShell failed (`gzip: stdin: not in gzip format`), so I used `scp -r` for the exact four artifact directories.
- Full smoke required local ignored fixture refresh: standard REPS artifacts were missing/stale in this worktree, so I pulled/regenerated them under `output/probe` and backfilled local artifact contract fields only.
- I did not run `git add`, `git commit`, `git push`, `cases_index.py`, DB backfill, `docs/cases/INDEX.md` update, N100 deploy, or service commands.
