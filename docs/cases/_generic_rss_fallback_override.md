---
slug: _generic_rss_fallback_override
url: batch://2026-05-28-games-indie-news-05
status: improved - post-LLM validated RSS/Atom fallback registers hybrid/rss sites
outcome: improved
date: 2026-05-28
failure_keys: [posts_nonempty, probe_grounding_list_row_selector, validated_feed_available]
fix_layer: F
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: [scripts/register.py, engine/transforms.py]
tags: [rss-fallback, atom-feed, gen_fail, batch]
requested_by: batch
---

## What Happened

Batch `2026-05-28-games-indie-news-05` had a repeated gen_fail pattern: the probe digest already had a validated RSS/Atom feed, `site_kind.kind` was `rss` or `hybrid`, but generation still attempted HTML rows from a landing/forum/root page and failed validation.

Catalog-entry evidence:

- `host_box2d-org_root_c360d996`: root HTML did not contain the real post list; validated `https://box2d.org/index.xml` had 22 RSS items.
- `host_community-plays_root_dc9ef028`: forum root was noisy; validated `https://community.playstarbound.com/forums/-/index.rss` had 6 RSS items.
- `host_randomascii-wor_root_f74fd8ea`: WordPress REST failed and HTML generation could fail; validated `https://randomascii.wordpress.com/feed/` had 10 RSS items.
- `host_adriancourreges_root_3a1e3b11`: static HTML rows exist, but slash date extraction was a separate transform bug; validated Atom feed existed as a fallback.

## Fix

`scripts/register.py` now has an F-layer fallback after exhausted generation fails and after `_generation_failure_reject_rc(...)` returns `None`. It only fires when:

- `digest.site_kind.kind in {"rss", "hybrid"}`
- `site_kind.primary_feed_url` matches a `feed_candidates[]` entry
- that feed candidate has `validated == true`, `item_count >= 3`, and `root_tag` is `rss` or `feed`

The fallback builds a minimal `httpx_html` XML config without another LLM call, then sends it through the existing built-config registration path for schema validation, list fetch, validation, config write, baseline state write, and stale marker cleanup.

RSS uses `channel > item`, text `<link>`, and RSS date formats. Atom uses `feed > entry`, `link[href]`, `id`, and `updated/published`. WordPress-style RSS GUIDs like `...?p=4211` are normalized to stable numeric IDs before falling back to path-like IDs.

`engine/transforms.py` also normalizes `/` to `-` in `date_only_to_iso`, so URL-derived dates like `2018/12/02` produce `2018-12-02T00:00:00<tz>`.

## Track B Audit

- E schema rejection: miss - configs were schema-valid enough to attempt runtime validation; no static schema rule would know the root HTML is the wrong source while the feed is validated.
- D retry feedback: miss - the retry feedback already reported row/grounding failures; the missing behavior was enforcement after generation ignored the feed route.
- C probe digest signal: hit-existing - probe already exposed `feed_candidates`, `root_tag`, `item_count`, and `site_kind.primary_feed_url`; no probe extraction change was needed.
- B few-shot: miss - prompt/examples already cover RSS dispatch, and the failure is that generation did not comply.
- A system rule: miss - prompt already says to use RSS/Atom where appropriate; adding another rule would not enforce it.
- F engine/register flow: hit - post-generation fallback can deterministically register validated feeds without relying on another model attempt.

## Regression Verification

- `pytest tests/engine/test_transforms.py tests/llm/test_register_auto_mode.py -q`: 13 passed.
- `python tests/probe_heuristics/test_site_kind.py`: 16 passed.
- `python scripts/register.py --reuse-probe "https://box2d.org/"`: rc=0, RSS fallback, baseline 22, `list.url_template=https://box2d.org/index.xml`.
- `python scripts/register.py --reuse-probe "https://community.playstarbound.com/"`: rc=0, RSS fallback, baseline 6, `list.url_template=https://community.playstarbound.com/forums/-/index.rss`.
- `python scripts/register.py --reuse-probe "https://randomascii.wordpress.com/"`: rc=0 after WordPress REST 404 fallback, RSS fallback, baseline 10, `list.url_template=https://randomascii.wordpress.com/feed/`.
- `python scripts/register.py --reuse-probe "https://adriancourreges.com/"`: rc=0, Atom fallback, baseline 20, `list.url_template=https://adriancourreges.com/atom.xml`.

Note: this dev environment had zero Gemini API keys, so the live register checks reached the fallback through LLM-call failure rather than through a model-produced invalid HTML config. The fallback gate still used the same post-`GenerationError`, post-rejection path.

## Self Check

1. Layer: F, because the behavioral change is in `scripts/register.py` registration control flow and `engine/transforms.py`.
2. Previous cases: SIGMOD, Scala, and multiple RSS/Atom hand configs showed the same stable-feed rescue shape.
3. Blast radius: only exhausted gen_fail paths with validated primary feeds and `rss|hybrid` site_kind; currently passing generation paths do not enter this branch.
4. Verification: targeted tests, four catalog-entry registrations, and stage smoke are recorded in this case or final handoff.
5. Outcome: improved, because future unknown hybrid/rss sites with validated feeds can recover without per-site config authoring.
6. Fixture: builder and transform unit tests added; no new strategy or probe heuristic fixture needed.
