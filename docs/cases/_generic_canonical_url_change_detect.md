---
slug: _generic_canonical_url_change_detect
url: (generic)
status: "✅ improved — canonical URL change detect + REJECTED hint"
outcome: improved
fix_layer: F
failure_keys: [canonical_url_change, article_404_list_200, redirect_hint]
date: 2026-05-27
trigger_slugs: [host_blog-filecoin-i_root_4ab2d2a3, host_blog-gnosis-io_root_65e050b1]
---

## Root Cause

Two `blog.<sub>` URLs still served a list page, but the canonical board moved to a different domain. The old subdomain article URLs returned 404, so register preflight had enough evidence to stop before LLM generation but previously only continued with an empty article reprobe.

- Filecoin: `https://blog.filecoin.io/` redirected/canonicalized toward `https://filecoin.io/blog`; article reprobe for `https://blog.filecoin.io/blog/Announcing-Filecoin-ProPGF-Batch-3-General-Track` returned 404.
- Gnosis: `https://blog.gnosis.io/` canonicalized to `https://www.gnosis.io/blog`; article reprobe for `https://blog.gnosis.io/blog/gnosis-ramp-beta` returned 404.

## Fix

F-layer in `scripts/register.py`:

- Persist preflight article reprobe status to `article.reprobe.json`.
- After preflight, if list page was HTTP 200 and article reprobe was 404, read list HTML canonical/`og:url`; fallback to redirect chain.
- If the canonical/redirect URL differs from the requested URL, write `.REJECTED.json` with `reason=canonical_url_change`, `hint=<new_url>`, and `learn=true`.
- `bot.site_ops.public_rejected_note()` appends a user-facing retry hint: `/watch <new_url>`.

## 6-Layer Audit

- E miss: config schema cannot see live preflight article 404 or list canonical redirects.
- D miss: retry feedback would still spend generation attempts; the evidence exists before generation.
- C miss: no new probe extraction is required. Existing `list.html` and preflight article status are enough; this is not a static/rendered/HAR candidate extraction gap.
- B miss: examples cannot deterministically reject a moved canonical URL before generation.
- A miss: prompt wording could teach suspicion, but it would still call the LLM and could produce unstable configs.
- F hit: `register.py` owns preflight control flow and rejected marker writes, so it can terminate cheaply with a canonical hint.

## Regression Verification

- Unit fixture: `tests/scripts/test_canonical_url_change_reject.py` covers list=200 + article=404 + canonical link => `.REJECTED.json` with `reason=canonical_url_change` and `hint`.
- UX fixture: `tests/bot/test_rejected_hint.py` covers the public note containing `URL이 바뀐 것 같아요` and `/watch <hint>`.
- Artifact pull: pulled `output/probe/<slug>` for both trigger slugs from N100 read-only with `scp`.
- Replay:
  - `python scripts/register.py "https://blog.filecoin.io/" --slug host_blog-filecoin-i_root_4ab2d2a3 --reuse-probe --force --max-attempts 1` stopped at preflight with `canonical=https://filecoin.io/blog`.
  - `python scripts/register.py "https://blog.gnosis.io/" --slug host_blog-gnosis-io_root_65e050b1 --reuse-probe --force --max-attempts 1` stopped at preflight with `canonical=https://www.gnosis.io/blog`.
- `python scripts/probe_smoke.py --stage 3 --stage 5` exited 0.
- `python scripts/vocab_lint.py` initially failed on pre-existing avoid-term hits outside this case/change; direct terminology replacements were applied.

## OLD vs NEW

- OLD: article reprobe printed 404/NOT_FOUND, then generation continued and failed as `gen_fail` or unrelated hub rejection.
- NEW: preflight writes `.REJECTED.json` immediately with `reason=canonical_url_change` and `hint`, so the user can retry `/watch <new_url>`.

## Impact

This only affects URLs where preflight has both a healthy list page and a 404 article reprobe, plus a differing canonical or redirect target. Existing registered configs are not changed.
