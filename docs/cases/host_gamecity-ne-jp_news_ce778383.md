---
slug: host_gamecity-ne-jp_news_ce778383
url: https://www.gamecity.ne.jp/news/
status: "🛠️ infra timeout fixed; probe/agentic selection fix pending deploy"
outcome: improved
date: 2026-05-26
fix_layer: D
failure_keys:
  - validate_internal_timeout
  - posts_nonempty
  - infra_feedback_misguidance
  - agentic_selection
  - probe_strategy_contradiction
  - transient_playwright_dns
config_strategy: playwright_html
tags:
  - batch-2026-05-24-games-jp
  - agentic
  - retry-feedback
  - validator-timing
---

# GAMECITY `/news/` Agentic Failure

## What Happened

Actual N100 batch retry after agentic workdir preservation showed three distinct failures.

First, before `3443f04`, validator runs inside Codex Linux `workspace-write` sandbox failed with
`Temporary failure in name resolution` and `net::ERR_NAME_NOT_RESOLVED`. The timing artifact showed
`httpx_get` consuming about 15s and the wrapper ending at `validate_internal_timeout_25s`. That was
not site slowness or selector burn; it was the agentic sandbox network environment.

Second, after the network fix, GAMECITY still failed. The preserved workdir:

- `failure_packet.json`: previous candidate was `playwright_html` with
  `#ajax_news > a.news-news-list__item`.
- `digest.json`: probe had real rendered rows at
  `#ajax_news > a.news-news-list__item.undefined`, `child_count=25`, sample URL
  `https://www.gamecity.ne.jp/news/28541.html`.
- `candidate.json`: agent switched to `httpx_html`, kept the rendered selector, and invented child
  selectors / JSON endpoint details. Static `s1.H*.html` does not contain those rows, so validator
  returned `posts_nonempty: 0건` in under 1s.

Root cause at that point: retry feedback treated an infra failure as proof that the strategy/selector
direction was bad, telling the agent to change direction. That pushed it away from the probe-grounded
Playwright direction.

Third, after the retry-feedback fix, N100 job `#3610` still failed:

- Probe succeeded with Playwright and found real rows under `#ajax_news > a.news-news-list__item`.
- The same probe also wrote a contradictory diagnosis: `recommended_strategy` was
  `httpx + 캡처된 메인 문서 헤더 (S1.Hcap)`, while `notes` said `정적 응답이 빈 shell` and
  `strategy=playwright_html 필수`.
- api-loop candidate correctly tried `playwright_html`, but validation hit a fast Chromium
  `Page.goto: net::ERR_NAME_NOT_RESOLVED` despite probe Playwright having just loaded the same URL.
- agentic then retried `httpx_html` with the rendered selector. Static HTML has no `#ajax_news` rows,
  so validation returned `posts_nonempty: 0건`.

Root cause of the remaining GAMECITY failure: probe and prompt input still allowed an `S1.Hcap` OK
shell to outweigh the stronger static-vs-headless evidence. The selector itself was not the problem;
it matched rendered `list.html`. The execution layer also needed one retry for transient Chromium DNS
failures so the correct Playwright candidate was not discarded after a 20ms browser navigation flake.

## Fix

- `generate/generator.py`: retry feedback now detects DNS/browser-launch infra failures and does not
  emit "change strategy/root selector" guidance for those failures.
- `prompts/register_agent_AGENTS.md`: agentic prompt now says infra failures in `failure_packet.json`
  are not selector evidence and tells the agent to prefer selectors/URLs that appear in `digest.json`.
- `probe/diagnose.py`: the static-vs-headless empty-shell check now evaluates `S1.Hcap` with the
  other static-like responses. If the best static-like response is still a shell, `S1.Hcap` is not
  allowed to win `recommended_strategy` or verdict.
- `prompts/config_writer.system.txt` and `prompts/register_agent_AGENTS.md`: if historical artifacts
  still contain a conflict, the empty-shell / `playwright_html 필수` note is explicitly stronger than
  `recommended_strategy=httpx/S1.Hcap`.
- `engine/strategies/playwright_html.py`: `Page.goto` retries once for transient DNS navigation
  failures (`ERR_NAME_NOT_RESOLVED`, `Temporary failure in name resolution`), without changing global
  navigation timeout or wait semantics.
- `tests/llm/test_retry_feedback.py`: locks the infra-feedback path, including attempt history and
  alternate strategy candidate sections.
- `tests/probe_heuristics/test_diagnose_static_hcap_contradiction.py` and
  `tests/probe_heuristics/test_playwright_transient_nav.py`: lock the GAMECITY-specific generic
  regressions without hard-coding the slug into production code.

## Regression Notes

Impact is generic to agentic fallback after api-loop infra failures. It does not hard-code GAMECITY
or force a strategy globally. It only prevents bad retry guidance when the observed failure is
network/browser infrastructure rather than extraction logic.

Pre-deploy checks after the first retry-feedback patch:

- `python -m pytest tests/llm/test_retry_feedback.py tests/llm/test_codex_agentic.py -q`
- `python tests/validate/test_article_fetch_budget.py`
- `python tests/scripts/test_capability_blocked_validate_timeout.py`
- `python scripts/probe_smoke.py --stage 3 --stage 5`

N100 job `#3610` proved the first retry-feedback patch was incomplete. The next verification must
deploy the probe/prompt/Playwright retry changes and rerun the actual batch URL, not a hand-written
minimal config.
