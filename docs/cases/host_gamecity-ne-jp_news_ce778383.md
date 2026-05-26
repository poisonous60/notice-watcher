---
slug: host_gamecity-ne-jp_news_ce778383
url: https://www.gamecity.ne.jp/news/
status: "✅ registered by generic JSON list/body API handoff; monthly fallback deferred"
outcome: improved
date: 2026-05-26
fix_layer: C+D
failure_keys:
  - validate_internal_timeout
  - posts_nonempty
  - infra_feedback_misguidance
  - agentic_selection
  - probe_strategy_contradiction
  - transient_playwright_dns
  - json_list_url_identity
  - monthly_json_api
config_strategy: httpx_json
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

Root cause after `#3610`: probe and prompt input still allowed an `S1.Hcap` OK
shell to outweigh the stronger static-vs-headless evidence. The selector itself was not the problem;
it matched rendered `list.html`. The execution layer also needed one retry for transient Chromium DNS
failures so the correct Playwright candidate was not discarded after a 20ms browser navigation flake.

Fourth, after deploying that fix, N100 job `#3611` proved the contradiction was gone:

- Verdict changed to `JS 실행 필요 (Cloudflare 등)` and recommended strategy changed to Playwright.
- The validator timing showed `goto_dom` attempt 1 and attempt 2 both failed quickly with
  `ERR_NAME_NOT_RESOLVED`; this is a repeated Chromium DNS failure, not a selector wait or timeout.
- The preserved agentic candidate then became invalid JSON (`candidate JSON parse failed`), so the
  agent did not recover to a different strategy.

The HAR contained the better path all along: `/js/news.js` builds monthly JSON URLs such as
`/cms-data/json/news_202605.json`, and the HAR recorded those responses. They were missing from
`traffic_json_api_candidates` because `find_list_in_json` only treated rows with `title/name` plus an
explicit `id/no/slug` key as post rows. GAMECITY rows use `name + link_url + date`, so the real latest
news JSON was filtered out while stale `access_ranking.json` survived.

Fifth, after deploying the JSON list signal fix, N100 job `#3613` showed the generic signal worked:

- `traffic_json_api_candidates` now included six candidates; the top three were the monthly news JSON
  files, each linked back to `/js/news.js` through `source_script_hints`.
- api-loop selected `httpx_json` for the list, but chose the HTML article page instead of the captured
  body JSON candidate `/cms-data/json/news/28541.json`.
- Validation no longer timed out. It failed quickly with `article_body_len` and then
  `fetch_article JSONDecodeError` after the retry candidate changed the article path incorrectly.

That left a generic agentic handoff issue: when `article_sample.api_candidates` has
`url_id_match=true`, `body_looks_html=true`, and a `body_field_path`, the agent should use that API for
`article.fetch_kind="json"` before trying HTML selectors. This is not specific to GAMECITY; it is the
same SPA-body pattern the preflight already tries to surface. The case frontmatter keeps cumulative
`fix_layer: C+D`: the JSON row-shape fix is C-layer, and this follow-up is D-layer agentic input.

Sixth, after deploying that agentic handoff fix, N100 job `#3623` passed through the real worker path:

- api-loop generated a `strategy="httpx_json"` config.
- list uses the captured monthly news JSON.
- article uses the captured body JSON API: `/cms-data/json/news/{post_id}.json` with
  `article.fetch_kind="json"` and `content` path `[0, "text_content"]`.
- Validation passed in the normal registration path and baseline registered 15 posts.

This is a real generic recovery of the SPA list/body API handoff. It is not a durable solution to the
monthly URL generation problem: the registered list URL is still the observed current-month
`news_202605.json`. `/js/news.js` proves the page computes current `YYYYMM` and falls back to older
months, so a future month will require either an engine-supported date/fallback URL surface or a
handwritten adapter. That broader engine surface was not added from this single site.

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
- `probe/hydration.py`: JSON list detection now accepts URL identity keys (`url`, `link`,
  `href`, `permalink`, `link_url`, `path`) as well as explicit id keys. This promotes
  `news_YYYYMM.json` style rows to `traffic_json_api_candidates`.
- `scripts/register.py` now tells the agent to inspect verified JSON API candidates before
  Playwright when static HTML is a shell but HAR shows a rendered-list JSON source.
- `prompts/register_agent_AGENTS.md`: agentic tmpdir instructions now carry the same list/body JSON
  API handoff rules directly, so the agent does not have to skim the full ruleset to learn that
  `source_script_hints` and `article_sample.api_candidates` are high-priority evidence.
- `tests/llm/test_retry_feedback.py`: locks the infra-feedback path, including attempt history and
  alternate strategy candidate sections.
- `tests/probe_heuristics/test_diagnose_static_hcap_contradiction.py` and
  `tests/probe_heuristics/test_playwright_transient_nav.py`: lock the GAMECITY-specific generic
  regressions without hard-coding the slug into production code.
- `tests/probe_heuristics/test_json_list_url_identity.py`: locks the JSON row-shape signal.
- `tests/llm/test_codex_agentic.py`: locks that the tmpdir `AGENTS.md` includes JSON list/body API
  handoff rules.

## Regression Notes

Impact is generic to agentic fallback after api-loop infra failures. It does not hard-code GAMECITY
or force a strategy globally. It only prevents bad retry guidance when the observed failure is
network/browser infrastructure rather than extraction logic.

Pre-deploy checks after the first retry-feedback patch:

- `python -m pytest tests/llm/test_retry_feedback.py tests/llm/test_codex_agentic.py -q`
- `python tests/validate/test_article_fetch_budget.py`
- `python tests/scripts/test_capability_blocked_validate_timeout.py`
- `python scripts/probe_smoke.py --stage 3 --stage 5`

Local verification of the possible stable path:

- A `httpx_json` config using
  `https://www.gamecity.ne.jp/cms-data/json/news_202605.json` validated successfully:
  15 posts, first article body 10326 chars.

Open question: this site JS computes `news_YYYYMM.json` from the current month and falls back to
previous months on 404. A hard-coded `news_202605.json` would become stale eventually, but adding a
generic date-token/fallback URL engine surface from this single site is too broad without another
same-pattern batch case. Keep it as a documented follow-up unless more sites show the same monthly
JSON pattern.

N100 verification after the agentic handoff prompt:

- Job `#3623`: `done`, rc=0.
- Registered config on N100:
  `/home/aaaa/notice-watcher/configs/host_gamecity-ne-jp_news_ce778383.json`.
- Caveat: that runtime config is an auto-generated N100 artifact and is not a generic code change.
