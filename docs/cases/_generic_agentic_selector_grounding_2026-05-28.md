---
slug: _generic_agentic_selector_grounding_2026-05-28
url: N/A
status: "✅ improved — agentic selector grounding and mixed article JSON support"
outcome: improved
date: 2026-05-28
fix_layer: A+F
failure_keys: [hashed_selector, probe_grounding_list_row_selector, article_json_api]
config_strategy: mixed
engine_files_touched: [generate/validate.py, engine/strategies/httpx_html.py, engine/strategies/playwright_html.py]
tags: [agentic, selector-grounding, css-in-js, json-api]
---

## 무엇이 일어났나
Five games batch failures had clean probe evidence but agentic retries still copied generated class selectors or ignored JSON API body candidates. The common symptom was max-cycle failure after repeated zero-row or body-length feedback.

## 왜 문제인가
Probe candidates are evidence, not selectors to copy verbatim. CSS-in-JS, `jss*`, and Material UI class stacks are brittle, while href prefixes and JSON endpoints were stable across the affected sites.

## 픽스 (fix_layer: A+F)
`prompts/config_writer.system.txt` now warns against copied generated selectors and instructs href-based row selectors plus Gatsby/Next/page-data JSON preference. `generate/validate.py` now includes the probe top selector, href prefix, sample URL, and `first_article_url` when grounding fails. HTML and Playwright strategies now honor `article.fetch_kind:"json"` by delegating article fetches to the JSON parser.

## 6-layer audit
- E schema: miss — schema already allowed `article.fetch_kind:"json"`.
- D retry feedback: partial — grounding failure text now includes concrete probe evidence, but no retry prompt builder file changed.
- C probe heuristic: miss — artifacts already exposed href prefixes and JSON API candidates.
- B few-shot: miss — no new example config needed for this narrow rule.
- A system prompt: hit — prompt now tells agentic not to copy generated class selectors.
- F engine: hit — mixed rendered-list plus JSON-article execution was missing.

## 회귀 검증
Per-site smoke passed for all five target configs:
- Bethesda www: list 5, first article body 12106 chars.
- Bethesda non-www: list 5, first article body 12106 chars.
- Epic Store: list 5, first article body 5508 chars.
- Epic www: list 5, first article body 5508 chars.
- Dead by Daylight: list 5, first article body 2799 chars.

Repo verification:
- `python scripts/probe_smoke.py --stage 3 --stage 5` → exit 0, summary `PASS 1739 FAIL 0 WARN 1 SKIP 0`.
- `python scripts/vocab_lint.py` → exit 0, `OK: scanned 406 file(s), 23 high-confidence rule(s)`.

`docs/cases/INDEX.md` and `output/cases.sqlite3` were intentionally not updated in this Codex handoff because the task hard-stopped `scripts/cases_index.py` / backfill work for the owner session.
