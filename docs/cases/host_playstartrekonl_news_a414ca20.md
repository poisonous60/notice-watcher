---
slug: host_playstartrekonl_news_a414ca20
url: https://playstartrekonline.com/news/
status: "improved — agentic prompt now blocks SVG/path fake rows"
outcome: improved
date: 2026-05-28
fix_layer: A+D
failure_keys: [probe_grounding_list_row_selector, probe_grounding_list_wait_selector, svg_path_selector, nav_only_candidates]
config_strategy: auto
engine_files_touched: []
prompt_files_touched: [prompts/config_writer.system.txt, prompts/config_writer.retry_skeleton.txt, prompts/register_agent_AGENTS.md]
tags: [batch-2026-05-28-games-online-live-service-03, agentic, selector-grounding]
---

# Star Trek Online news — SVG selector hallucination

## Evidence

Failure marker: `failed_at=2026-05-28T03:54:14Z`; last feedback was `probe_grounding_list_row_selector: 0 nodes` then `probe_grounding_list_wait_selector: 0 nodes`. The last config used `playwright_html` with `row_selector="#Group_450 > path"` and `wait_selector="#Group_450 > path"`, then hard-coded article URL `https://www.playstartrekonline.com/en/download`.

Live/probe evidence: local probe returned 200 for static and rendered entry. Diagnosis: `JS 실행 필요 (Cloudflare 등)`, with note that the static response is an empty shell and `strategy=playwright_html` is required. Candidates were nav/footer/menu/SVG dominated: `div.arcui-footer-section__links > a...`, `div.arcui-menu-list > a...`, `div.arcui-header-component > a...` with sample `/en/news`, and decorative `#Group_450 > path` / `g > path` with empty text and no article URL.

Preflight: no config exists; recognizer miss; commit `66de590` touched prompt/engine/probe/generate after the failure timestamp. The probe artifact was missing from N100 pull and was regenerated locally.

## Screen-out

P1/P2/P3: no direct match. The submitted URL looks like an official news route, but the current probe evidence does not expose article rows, only nav/footer/SVG and a client route to `/en/news`.

## Track B 6-layer audit

- E schema: miss — `#Group_450 > path` is syntactically valid CSS, so schema alone cannot know it is decoration.
- D retry feedback: hit — repeated `probe_grounding_* 0 nodes` should instruct the model to discard fake selectors, especially SVG/path selectors.
- C probe heuristic: partial/miss for this patch — the artifact exposes SVG/path candidates but does not provide a real article row to promote; no new C heuristic is safe in this chunk.
- B few-shot: miss — an example would not fix the general hallucination failure.
- A system prompt: hit — config writer and agentic tmpdir prompts now explicitly reject SVG/icon/decorative candidates and fake configs.
- F engine/recognizer: miss — a Star Trek Online recognizer/manual route would be site coverage without ship evidence.

## Cross-site pattern

Same failure family as Halo: agentic treated visual SVG/path DOM as a board row. Star Trek is the stricter case because the probe has no clear article-row fallback; the correct generic behavior is to stop rather than invent `#Group_450 > path` and `/en/download`.

## Outcome

Outcome is `improved`: the generic A+D prompt change prevents this class of fake-row config from being emitted. It may still leave this specific site unresolved until a real article source is discovered; no per-site config or terminal marker was written.
