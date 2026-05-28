---
slug: host_adriancourreges_root_3a1e3b11
url: https://adriancourreges.com/
status: improved - slash date transform fixed; validated Atom fallback registered baseline
outcome: improved
date: 2026-05-28
failure_keys: [published_at_iso, date_only_to_iso_slash, validated_feed_available]
fix_layer: F
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: [engine/transforms.py, scripts/register.py]
tags: [slash-date, atom-feed, rss-fallback]
requested_by: batch
---

## What Happened

The failed run had working static HTML rows under `div.projectGrid > a.projectThumbnail.flex-content`, but the generated config extracted dates from article URLs as slash-separated paths like `2018/12/02`. `date_only_to_iso` only preserved the string as-is, so validation saw `2018/12/02T00:00:00+...` and failed `published_at_iso`.

The submitted URL also has a live `www` canonical in content/feed links. Local probe followed enough redirects to capture the working page and found the first article URL:

`https://adriancourreges.com/blog/2018/12/02/ue4-optimized-post-effects/`

## Fix

`engine/transforms.py` now normalizes slash dates before formatting:

`2018/12/02 -> 2018-12-02T00:00:00<tz>`

The same run also benefits from the generic RSS/Atom fallback in `scripts/register.py`: after generation failed in this dev environment because there were zero Gemini API keys, the validated Atom feed at `https://adriancourreges.com/atom.xml` registered through `feed > entry`.

No per-site selector tweak was added.

## Track B Audit

- E schema rejection: miss - slash dates are runtime extracted values, not config schema shape.
- D retry feedback: miss - feedback could say `published_at_iso`, but the transform itself lacked a common normalization.
- C probe digest signal: miss - probe already exposed the URL path and feed; no new digest signal was needed.
- B few-shot: miss - asking the model to insert `replace("/", "-")` everywhere is weaker than making the named date transform accept the common format.
- A system rule: miss - this is transform vocabulary behavior, not a prompt rule gap.
- F engine/register flow: hit - `date_only_to_iso` behavior changed, and validated Atom fallback can recover exhausted gen_fail paths.

## Regression Verification

- `pytest tests/engine/test_transforms.py tests/llm/test_register_auto_mode.py -q`: 13 passed.
- `python scripts/register.py --reuse-probe "https://adriancourreges.com/"`: rc=0, Atom fallback, baseline 20, `list.url_template=https://adriancourreges.com/atom.xml`, `row_selector=feed > entry`.
- Generated baseline sample used live `www` article links from Atom and parsed dates like `2018-12-02T11:24:00+01:00`.

Limitation: because this dev environment had zero Gemini API keys, this run did not re-prove the HTML `projectThumbnail` config path. The slash-date behavior is covered by the transform regression test.

## Self Check

1. Layer: F, because both changes are engine/register code.
2. Previous cases: slash dates are a recurring URL-derived date shape; Atom/RSS fallback is covered by the generic case.
3. Blast radius: `date_only_to_iso` keeps existing hyphen dates unchanged and only normalizes `/` to `-`.
4. Verification: targeted transform/builder tests and live register rc=0.
5. Outcome: improved, because future URL-derived slash dates no longer need an extra generated `replace` step.
6. Fixture: transform test added; no per-site fixture required.
