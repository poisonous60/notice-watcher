---
slug: host_halowaypoint-co_news_414e9d1d
url: https://halowaypoint.com/news/
status: "improved — agentic retry guidance now rejects decorative SVG/path rows"
outcome: improved
date: 2026-05-28
fix_layer: A+D
failure_keys: [probe_grounding_list_row_selector, first_article_url_mismatch, svg_row_noise, hashed_selector]
config_strategy: auto
engine_files_touched: []
prompt_files_touched: [prompts/config_writer.system.txt, prompts/config_writer.retry_skeleton.txt, prompts/register_agent_AGENTS.md]
tags: [batch-2026-05-28-games-online-live-service-03, agentic, selector-grounding]
---

# Halo Waypoint news — SVG noise and stale CSS-module selector

## Evidence

Failure marker: `failed_at=2026-05-28T04:08:47Z`; last feedback was `published_at_iso; first_article_url mismatch` then `probe_grounding_list_row_selector: 0 nodes`. The last config chose `httpx_html` with `row_selector="a.featured-article-small-archive_article_small_archive___ZD7G"`, a Next/CSS-module class that did not match the probe grounding HTML.

Live/probe evidence: local probe rerun on 2026-05-28 returned 200 for static HTTP and diagnosed `정적 HTTP로 충분`, first article `https://halowaypoint.com/news/halo-fest-may`, HTML candidates 4, JSON API candidates 2. Current C-layer row scoring ranks the real row first: `section.featured-articles_featured-articles__bjMo1 > a.featured-article-small_article_small__woUT9`; SVG candidates `g > path.st0` and `#Layer_1 > g` are now below it.

Preflight: no `configs/host_halowaypoint-co_news_414e9d1d.json`; recognizer miss; no committed prompt/engine/probe changes after the failure timestamp. The probe artifact was present after read-only triage pull, then refreshed locally for live evidence.

## Screen-out

P1/P2/P3: no match. This is a real official news board, not a single article, not a not-found shell, and not an empty/fake feed.

## Track B 6-layer audit

- E schema: miss — the candidate is schema-valid; whether a selector is decorative/stale needs probe/validator context.
- D retry feedback: hit — `probe_grounding_list_row_selector: 0 nodes` should tell the model to discard that selector family and choose an article-text/sample-url candidate, not tweak the same hash class.
- C probe heuristic: existing hit in this branch — current probe row scoring demotes SVG/path candidates and promotes the article row.
- B few-shot: miss — a Halo-specific example would teach one template, not the generic "SVG/path is not a row" failure.
- A system prompt: hit — config writer rules now explicitly ban SVG/icon/decorative `g/path/#Layer/#Group` candidates and unsupported `regex_replace`.
- F engine/recognizer: miss — no Halo recognizer or strategy change is needed for this audit.

## Cross-site pattern

Same family as `host_playstartrekonl_news_a414ca20`: probe/agentic saw high-count SVG/path candidates and the generated config chased decorative DOM instead of article rows. The generic fix belongs in A/D-layer prompt and retry feedback, not a hand-written Halo config.

## Outcome

Outcome is `improved`: this case contributed to a generic A+D prompt change that prevents future agentic retries from treating SVG/path decoration as list rows. No per-site config was written; batch ship evidence is 0, so Track A stays closed.
