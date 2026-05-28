---
slug: host_oldschool-runes_root_2ff8b508
url: https://oldschool.runescape.com/
status: "no_change — true board but no new generic fix beyond existing DNS/selector guidance"
outcome: no_change
date: 2026-05-28
fix_layer: none
failure_keys: [err_name_not_resolved, title_empty, cloudflare_rendered_board, nav_first_article]
config_strategy: none
engine_files_touched: []
tags: [batch-2026-05-28-games-online-live-service-03, cloudflare, no-ship]
---

# Old School RuneScape root — rendered board with nav first-article noise

## Evidence

Failure marker: `failed_at=2026-05-28T04:11:04Z`; last feedback was `ERR_NAME_NOT_RESOLVED` then `title empty; row selector matched news cards`. The last config used `playwright_html`, `disable_stealth:true`, and `section.content > article.news-article`.

Live/probe evidence: local probe had static HTTP 200 but `BLOCKED_BOT` on S1.H1-H4 and `S1.Hcap`; Playwright S4 returned 200 OK and cleared the Cloudflare interstitial. Diagnosis: `JS 실행 필요 (Cloudflare 등)`, recommended `Playwright headless + stealth (S4)`. Probe candidates showed nav first (`ul.home-nav__list > li`, sample `/polls`) and the real news row second (`section.content > article.news-article`, sample `https://secure.runescape.com/m=news/summer-campfire---announcement?oldschool=1`).

Preflight: no config exists; recognizer miss; no committed prompt/engine/probe changes after the failure timestamp. The probe artifact was missing from N100 pull and was regenerated locally.

## Screen-out

P1/P2/P3: no match. This is a real official news surface with repeated rendered news cards; it is not a single content page, not a not-found shell, and not a fake feed.

## Track B 6-layer audit

- E schema: miss — the config shape is valid.
- D retry feedback: miss for this task — existing DNS-race guidance already says infra failure is not selector evidence, and this candidate already had `disable_stealth:true`.
- C probe heuristic: miss — the probe does expose the real news row; the first-article nav pick is noisy but not enough here to justify another broad probe heuristic in this chunk.
- B few-shot: miss — a RuneScape-specific example would be site coverage, not generic improvement.
- A system prompt: miss — existing rules already say nav/menu candidates are not article rows; the new SVG/path wording does not materially change this site.
- F engine/recognizer: miss — a dedicated RuneScape recognizer/manual config would be Track A/site coverage, and batch operator flow has ship default false.

## Cross-site pattern

This site is the odd one out in the 4-site peer set. It shares "agentic selected the wrong candidate" symptoms, but the concrete signals are Cloudflare/DNS plus nav-vs-news selection, not the SVG/path hallucination seen on Halo/Star Trek or transform-vocab issue seen on SWTOR.

## Outcome

Outcome is `no_change`: all six Track B layers miss for this chunk, and ship evidence is 0. Park bucket would be true-board/no-ship (`triage_later.json`) for the owner session, but this handoff hard-stops terminal marker edits, so no marker was written.
