---
slug: _generic_url_dead_gates_2026-05-27
date: 2026-05-27
outcome: improved
fix_layer: C+F
status: url_dead gate improvements for cross-host redirect / parked Access Denied / probe-timeout-host-dead
failure_keys:
  - cross_host_redirect
  - parked_access_denied
  - probe_timeout_host_dead
tags: [url_dead, gate, generalization, batch-2026-05-24-games-official]
---

## Summary

Batch `2026-05-24-games-official` exposed three dead-URL patterns that were leaking into `gate_reject`, `capability_blocked`, or `gen_fail` instead of rc=4 `url_dead`.

This is a generic C+F fix:
- C hit: probe now preserves `Result.final_url`, diagnoses cross-eTLD+1 redirects, and classifies parked-domain Access Denied / JS lander shells as `NOT_FOUND`.
- F hit: register policy treats `CROSS_HOST_REDIRECT` as url_dead, and probe subprocess timeout does an 8s HEAD baseline check before falling back to rc=1.

## Pattern 1 - cross-host redirect

Input URLs returned 200 after redirecting to another registrable domain, so the old pipeline saw a reachable page and let normal board gates reject later.

Observed catalog entries:

| Input URL | Final URL | Old rc |
|---|---|---|
| `https://slaythespire.com/news/` | `https://megacrit.com/` | 3 |
| `https://slaythespire.com/` | `https://megacrit.com/` | 3 |
| `https://wolfenstein.com/` | `https://bethesda.net/ko/game/wolfenstein-youngblood` | 3 |
| `https://wolfenstein.com/news/` | `https://bethesda.net/ko/game/wolfenstein-youngblood` | 3 |
| `https://dontstarvegame.com/` | `https://www.klei.com/games/dont-starve/` | 3 |
| `https://fallout76.com/` | `https://fallout.bethesda.net/ko` | 3 |
| `https://fallout76.com/news/` | `https://fallout.bethesda.net/ko` | 1 |
| `https://starfield.bethesda.net/` | `https://bethesda.net/ko/game/starfield` | 3 |
| `https://starfield.bethesda.net/news/` | `https://bethesda.net/ko/game/starfieldnews` | 3 |
| `https://gears5.com/` | `https://www.gearsofwar.com/games/gears-5/` | 3 |
| `https://gears5.com/news/` | `https://www.gearsofwar.com/games/gears-5/` | 3 |
| `https://vampire-survivors.com/` | `https://beacons.ai/poncle` | 3 |

Guardrails covered by tests:
- `example.com` -> `www.example.com` is not cross-host because eTLD+1 is unchanged.
- `warthunder.com` -> `warthunder.com/en` is not cross-host because host is unchanged.
- `starfield.bethesda.net` -> `bethesda.net/game/starfield` is same eTLD+1 and intentionally not covered by this pass.

## Pattern 2 - parked Access Denied

`lethalcompany.com` and `contentwarning.com` returned short JS shells that redirected to `/lander`; `/lander` served an Access Denied parked-domain page. The old classifier treated this as bot/capability blocking.

The new signal is body-marker based, not host-list based:
- short `window.location.href="/lander"` shell -> `NOT_FOUND`
- short HTML `<title>Access Denied</title>` parked page -> `NOT_FOUND`
- long real auth/403 pages are not folded by this marker.

## Pattern 3 - probe timeout with dead baseline

`hadesgame.com` root and `/news/` timed out at the probe subprocess level and fell through to rc=1 `gen_fail`.

On `RegisterTimeoutError`, register now does a cheap baseline `HEAD` against the origin root with an 8s timeout. Connect/DNS/read/protocol failure on that baseline is saved as `REJECTED` with rc=4 and note `probe-timeout-host-dead`.

## Layer Audit

- E schema: miss - no config validation issue.
- D retry feedback: miss - failures happen before config retry feedback matters.
- C probe digest signal: hit - `final_url`, redirect verdict, parked-domain classification.
- B few-shot: miss - no config pattern to teach.
- A system prompt: miss - not an LLM interpretation problem.
- F engine/register flow: hit - rc=4 mapping for cross-host redirect and timeout baseline check.

## Verification

Red tests first:
- `test_diagnose_cross_host_redirect` failed on missing `Result.final_url`.
- `test_register_url_dead_policy` failed on missing timeout-baseline helper.
- `test_signals_classify` failed for parked Access Denied and JS lander shells.

Green after fix:
- `python tests/probe_heuristics/test_diagnose_cross_host_redirect.py`
- `python tests/probe_heuristics/test_register_url_dead_policy.py`
- `python scripts/probe_smoke.py --stage 5 --verbose`
- `python scripts/probe_smoke.py --stage 3 --stage 5`
- `python scripts/vocab_lint.py`

## Escalate / Defer

- Same eTLD+1 subdomain-to-parent folds, such as `starfield.bethesda.net` -> `bethesda.net/...`, are not closed by the eTLD+1-only rule and should be considered separately if they remain noisy.
- `_registrable_domain` uses a small built-in multi-label suffix list, not the full public suffix list, to avoid adding a dependency in this patch.
- No N100 artifact pull was attempted; this change was driven from the provided batch evidence and offline unit fixtures.
