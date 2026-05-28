---
slug: host_indiedb-com_news_537bc4e7
url: https://indiedb.com/news/
status: "handcrafted - IndieDB news RSS config + DBolical recognizer"
outcome: handcrafted
date: 2026-05-28
fix_layer: F
failure_keys: [cloudflare_challenge, rss_feed_available, agentic_max_cycles]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: [engine/recognizers/dbolical.py]
tags: [games-indie-news-06, indiedb, moddb, dbolical, rss, cloudflare]
requested_by: user
---

## Summary

IndieDB `/news/` is a real news board, but the HTML surface is Cloudflare-sensitive and agentic failed after trying the challenged HTML route. The stable source is DBolical's RSS endpoint:

`https://rss.indiedb.com/news/feed/rss.xml`

The fix keeps the requested failed slug config for immediate registration and adds an F-layer recognizer for the shared DBolical top-level news board pattern covering IndieDB and ModDB. Desura was checked but excluded: `rss.desura.com` did not resolve from this dev box, so there is no live feed evidence for that host.

## Evidence

- User ship evidence: "https://www.indiedb.com/news/ ?? ??? ? ???." The requested URL and slug match this case: `host_indiedb-com_news_537bc4e7`.
- Preflight: miss - no local `configs/host_indiedb-com_news_537bc4e7.json`, no existing IndieDB/ModDB recognizer, and `recognize("https://www.indiedb.com/news/")` returned `null`.
- N100 probe artifact pulled with `python scripts/triage.py pull host_indiedb-com_news_537bc4e7`. The command succeeded via one SSH tar stream and populated `output/probe/host_indiedb-com_news_537bc4e7/`.
- Probe verdict: `CLOUDFLARE_PROTECTED_SITE / 정적 HTTP로 충분`; B1/B2 and S1.H2/S1.H3 were 403 bot challenges; S1.H4 was 200 OK; S1.H4.article was 200 OK.
- Probe list signal: `HTML 10건 ... 첫 글: https://indiedb.com/news/the-challenge-of-adblock`.
- Probe feed signal: `feed_candidates.json` found `https://rss.indiedb.com/news/feed/rss.xml`, but N100 validation hit 403 because it fetched the RSS host without the live-friendly path used here.
- Live RSS check from dev box: `https://rss.indiedb.com/news/feed/rss.xml` returned 200 `application/rss+xml;charset=utf-8`, 10 `<item>` rows, first guid `articles347196`, first link `https://www.indiedb.com/games/equation-of-humanity/news/under-honor-games-authority`.
- Live HTML check from dev box: generic `Mozilla/5.0` on `https://www.indiedb.com/news` returned 403 with `Cf-Mitigated: challenge`; earlier curl with a mobile UA returned 200 for the board, but article links remained challenge-prone from this IP.
- Header root cause: Chrome-like `User-Agent` on `rss.indiedb.com` returned 403 challenge; bare httpx and `notice-watcher/1.0 (+polite)` returned 200 RSS XML.

## Config

`configs/host_indiedb-com_news_537bc4e7.json` polls the RSS XML with `strategy: "httpx_html"`:

- `list.url_template`: `https://rss.indiedb.com/news/feed/rss.xml`
- `headers.User-Agent`: `notice-watcher/1.0 (+polite)` because browser-like UA values trigger Cloudflare on the RSS host
- `row_selector`: `channel > item`
- `post_id`: RSS `guid`, fallback to the article slug from `link`
- `title`, `url`, `published_at`, `summary`, `cover_image`: RSS item fields
- `article.skip_status`: `[403]`
- `article.body_empty_acceptable`: `true`
- `article.content`: DBolical body selectors from the successful probe (`div#articlecontent`, `article div.bodyarticle`, `div.bodyarticle`)

The RSS summary keeps alerts useful even when Cloudflare blocks article body fetches.

## Track B 6-Layer Audit

| Layer | Fit | Reason |
|---|---|---|
| E schema rejection | miss | Existing schema already expresses RSS XML polling, 403 article skip, and optional body. |
| D retry feedback | miss | The retry tail already exposed Cloudflare and article/fetch failures; more feedback would not force the known DBolical RSS endpoint. |
| C probe digest | miss | Probe found static HTML rows and the RSS URL; the missing piece is known-platform enforcement, not a new probe signal. |
| B few-shot | miss | A sample might teach RSS selectors, but this is a specific platform family with deterministic feed URL construction. |
| A system rule | miss | Prompt guidance still leaves the LLM free to choose challenged HTML. A rule is weaker than pre-LLM recognizer dispatch for this known platform. |
| F engine | hit | `engine/recognizers/dbolical.py` now maps IndieDB/ModDB `/news` and direct RSS URLs to the stable RSS config. |

## Generic Pattern

- Name: DBolical news RSS.
- Scope: top-level `indiedb.com/news` and `moddb.com/news`, plus direct `rss.<host>/news/feed/rss.xml`.
- Fix layer: F.
- Same pattern evidence: IndieDB RSS live 200 with 10 items; ModDB RSS live 200 with 10 items through Python/httpx. `curl -I` can be challenged, so validation uses GET semantics.
- Excluded: article URLs under `/games/<game>/news/<slug>` and Desura DNS-missing RSS host.
- Separate worktree needed: no. The recognizer is host- and path-gated and the direct IndieDB config preserves the requested failed slug.

## Regression Verification

- `python tests/recognizers/test_dbolical.py`: PASS, 10 checks.
- `python scripts/register.py --config configs/host_indiedb-com_news_537bc4e7.json`: PASS, baseline 10. First ids: `articles347196`, `articles347192`, `articles347188`.
- Register warning: article bodies were not extracted from this dev IP due Cloudflare, so alerts are title/URL/RSS-summary based. This is intentional via `article.skip_status: [403]` and `body_empty_acceptable: true`.
- `python scripts/probe_smoke.py --stage 3 --stage 5`: PASS, exit 0. Stage 3 `305 / 305 OK`; stage 5 `139` files, `1473` cases, `0 FAIL`, `1 WARN` (`test_worker_failure_routing` has no `run()` protocol).

## Self Check

1. Layer: F. This is known-platform dispatch plus one direct config for the user-requested failed slug.
2. Previous cases: ModDB sibling exists in the same DBolical family; current checkout had no merged recognizer/config, so this case adds the family route.
3. Blast radius: limited to `indiedb.com/news`, `moddb.com/news`, and direct matching RSS URLs. Same-host article URLs are negative-tested.
4. Verification: recognizer unit, direct config registration, and stage 3/5 smoke.
5. Outcome: handcrafted, because this is platform coverage and a direct config, not generic unknown-structure inference.
6. Fixture: `tests/recognizers/test_dbolical.py` covers positive, direct RSS, schema, and negative URL cases.

## Park Branch

Not applicable. This case has explicit ship evidence and a working RSS source.
