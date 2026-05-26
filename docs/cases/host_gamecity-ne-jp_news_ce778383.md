---
slug: host_gamecity-ne-jp_news_ce778383
url: https://www.gamecity.ne.jp/news/
status: "🛠️ infra timeout + retry feedback fixed; N100 rerun pending"
outcome: improved
date: 2026-05-26
fix_layer: D
failure_keys:
  - validate_internal_timeout
  - posts_nonempty
  - infra_feedback_misguidance
  - agentic_selection
config_strategy: playwright_html
tags:
  - batch-2026-05-24-games-jp
  - agentic
  - retry-feedback
  - validator-timing
---

# GAMECITY `/news/` Agentic Failure

## What Happened

Actual N100 batch retry after agentic workdir preservation showed two distinct failures.

First, before `3443f04`, validator runs inside Codex Linux `workspace-write` sandbox failed with
`Temporary failure in name resolution` and `net::ERR_NAME_NOT_RESOLVED`. The timing artifact showed
`httpx_get` consuming about 15s and the wrapper ending at `validate_internal_timeout_25s`. That was
not site slowness or selector burn; it was the agentic sandbox network environment.

Second, after the network fix, GAMECITY still failed once. The preserved workdir:

- `failure_packet.json`: previous candidate was `playwright_html` with
  `#ajax_news > a.news-news-list__item`.
- `digest.json`: probe had real rendered rows at
  `#ajax_news > a.news-news-list__item.undefined`, `child_count=25`, sample URL
  `https://www.gamecity.ne.jp/news/28541.html`.
- `candidate.json`: agent switched to `httpx_html`, kept the rendered selector, and invented child
  selectors / JSON endpoint details. Static `s1.H*.html` does not contain those rows, so validator
  returned `posts_nonempty: 0건` in under 1s.

Root cause of the remaining GAMECITY failure: retry feedback treated an infra failure as proof that
the strategy/selector direction was bad, telling the agent to change direction. That pushed it away
from the probe-grounded Playwright direction.

## Fix

- `generate/generator.py`: retry feedback now detects DNS/browser-launch infra failures and does not
  emit "change strategy/root selector" guidance for those failures.
- `prompts/register_agent_AGENTS.md`: agentic prompt now says infra failures in `failure_packet.json`
  are not selector evidence and tells the agent to prefer selectors/URLs that appear in `digest.json`.
- `tests/llm/test_retry_feedback.py`: locks the infra-feedback path, including attempt history and
  alternate strategy candidate sections.

## Regression Notes

Impact is generic to agentic fallback after api-loop infra failures. It does not hard-code GAMECITY
or force a strategy globally. It only prevents bad retry guidance when the observed failure is
network/browser infrastructure rather than extraction logic.

Pre-deploy checks:

- `python -m pytest tests/llm/test_retry_feedback.py tests/llm/test_codex_agentic.py -q`
- `python tests/validate/test_article_fetch_budget.py`
- `python tests/scripts/test_capability_blocked_validate_timeout.py`
- `python scripts/probe_smoke.py --stage 3 --stage 5`

N100 rerun is required after deployment because the fixed text affects the live agentic prompt.
