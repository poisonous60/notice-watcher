---
slug: host_swtor-com_info_9b40c5ef
url: https://www.swtor.com/info/news/
status: "improved — transform vocabulary rule made explicit"
outcome: improved
date: 2026-05-28
fix_layer: A
failure_keys: [unknown_regex_replace, missing_post_id, post_id_unique, drupal_news_rows]
config_strategy: auto
engine_files_touched: []
prompt_files_touched: [prompts/config_writer.system.txt]
tags: [batch-2026-05-28-games-online-live-service-03, transform-vocab, drupal]
---

# SWTOR news — unsupported transform vocabulary and duplicate ID retry

## Evidence

Failure marker: `failed_at=2026-05-28T03:55:28Z`; last feedback was `build_adapter: missing post_id; unknown regex_replace` then `post_id_unique: duplicate 1 post`. The last config used `httpx_html` and the real Drupal-ish row selector `#news-media-list > div.newsItem.new`, but earlier generation used unsupported `regex_replace`.

Live/probe evidence: local probe returned static 200 and diagnosis `정적 HTTP로 충분`; top candidates included nav `ul.menu.holonet > li.leaf` and the real news row `#news-media-list > div.newsItem.new` with sample `https://www.swtor.com/info/news/%5Bnews-category%5D/20260527`. Feed candidate `https://www.swtor.com/feed/news` was link-rel Atom. Robots crawl-delay was 10 seconds.

Preflight: no config exists; recognizer miss; commit `66de590` touched prompt/engine/probe/generate after the failure timestamp. The probe artifact was missing from N100 pull and was regenerated locally.

## Screen-out

P1/P2/P3: no match. This is a real official news board with repeated article rows and static HTML evidence.

## Track B 6-layer audit

- E schema: hit existing — `engine/config_schema.py` already rejects unknown transforms and surfaced `unknown regex_replace`.
- D retry feedback: miss — duplicate post_id guidance already exists; this case does not need a new retry recipe.
- C probe heuristic: miss — the real row candidate is already present; nav noise is visible but not the root failure.
- B few-shot: miss — transform vocabulary is a rules issue, not an example issue.
- A system prompt: hit — the config writer prompt now explicitly says `regex_replace` is unsupported and maps likely intent to `regex_extract`, `replace`, `remove_prefix`, or `strip`.
- F engine/recognizer: miss — no new transform or SWTOR recognizer is needed for this audit.

## Cross-site pattern

This is not the same SVG selector failure as Halo/Star Trek, but it is the same broader agentic verdict-hallucination class: the model invented vocabulary outside the declared config DSL. Because E already catches the bad config, the minimal generic lift is A-layer vocabulary clarity rather than adding `regex_replace` to the engine.

## Outcome

Outcome is `improved`: the DSL vocabulary rule is now explicit in the system prompt. No per-site config was written; batch ship evidence is 0, so Track A remains closed.
