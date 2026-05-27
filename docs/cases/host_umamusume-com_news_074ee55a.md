---
slug: host_umamusume-com_news_074ee55a
url: https://umamusume.com/news/
status: ✅ handcrafted
outcome: handcrafted
date: 2026-05-28
fix_layer: none
failure_keys: [svelte_spa_shell, session_gated_post_api, posts_nonempty_zero, schema_missing_root]
config_strategy: playwright_html
engine_files_touched: []
adapters_changed: []
tags: [svelte, spa, post-api, session-bound, cygames, batch-2026-05-28-games-gacha-global-02]
requested_by: user
vocab_candidates: []
---

# umamusume.com /news/ — Svelte SPA shell, list comes from a session-bound POST API

## root cause

`https://umamusume.com/news/` is a Svelte SPA served from S3+CloudFront. The static HTML (`s1.H2.html`, 15.7 kB) is a
shell — class names like `ul.news-list.svelte-rnlpst > li.news-item.-type-news.-game.svelte-1ufvo21` appear in the
build, but no row markup is present in the initial document. The list is rendered after the SPA boots and issues
`POST https://umamusume.com/api/ajax/pr_info_index?format=json` (with an empty body). The HAR captured during probe
shows a 25.9 kB JSON response containing `information_list[]` — but a standalone `curl` POST against the same endpoint
returns `{"response_code":102}` (21 bytes), even with full browser headers including Origin/Referer. The API is
session-gated: it requires the OneTrust consent cookie state that the SPA establishes during navigation.

The autogen runs reflected this:

- `api_loop` attempt 1 → "0 posts; selector compiled but extracted nothing" (LLM picked `httpx_json` against
  `/api/ajax/pr_info_index?format=json` using GET; engine GETs are 404/empty for this POST-only endpoint).
- Agentic escalation → "schema missing version/site/board" then "root strategy/site/board type mismatch" — the
  POST-API rabbit hole led the agent into invalid config shapes; it exhausted cycles.

Net effect: `posts_nonempty 0` despite a real list of 10–13 news entries reachable through `playwright`.

## Track B 6-layer audit

- **E** schema 거부: miss — config shape is valid (validated after the manual write).
- **D** retry feedback: miss — feedback did include "0 posts" and the schema-shape errors. The agent saw them; the
  blocker is that `httpx_json` does not speak POST and probe didn't surface a "use playwright" signal strongly enough.
- **C** probe digest 신호: miss for this patch — a plausible heuristic is "if the only list source is a POST API whose
  body responds 102/empty without browser session, flag `render_required=true`". This is a single sample today; deferred.
- **B** few-shot: miss — no extra example would inform a "switch from POST httpx_json to playwright_html" decision; it
  is a strategy choice, not selector cloning.
- **A** system rule: miss for this patch — a one-liner like "if the JSON API uses POST without payload, prefer
  playwright_html with wait_selector on the rendered list" is a candidate but I avoid adding without a second slug to
  corroborate ([[feedback-orchestration-mistakes-permanent-gate]] still applies — one site is not a cross-site signal).
- **F** engine code: miss — `httpx_json` does not currently support POST; the deferred F-layer candidate is "POST
  support in `engine/strategies/httpx_json.py`" but even with POST added, this site needs the browser session, so it
  alone does not unblock umamusume. Recorded as a separate idea; not in this PR.

All six layers miss → §2 강제 인용 4b (a) satisfied.

## ship evidence

User instruction this turn: `차단된거나 게이트 거부 당한 건 신경쓰지 말고 gen_fail 된 것만 사이트 파악하고 처리해줘. … 일반화 시도해보고 정 안되면 수동 config라도 짜보던가.` followed by `/goal 우선 말해두자면 셋 다 게시판이기는 해. 일반화로 해결할 수 있으면 좋을 것 같지만, 안 되겠으면 수동 config라도 지원해줘.` umamusume.com/news/ is one of the three gen_fail slugs the user explicitly directed to ship via manual config when generalization is not on the table. §2 강제 인용 4b (b) satisfied.

## fix

`configs/host_umamusume-com_news_074ee55a.json`:

- `strategy: playwright_html` — only the browser session can materialize the list; the static HTML and the standalone
  POST are both empty.
- `wait_selector: ul.news-list li.news-item` — anchors to the post-hydration DOM.
- `row_selector: ul.news-list li.news-item` — same selector; 10 rows.
- `post_id` from `a[href]` capturing `/news/(\d+)` (article IDs are bare integers, e.g. 807, 100068).
- `title` from `dt` inside the row's `<dl>`.
- `published_at` from `<time>` with chain `collapse_ws → regex_extract "(\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2})" →
  replace "  " " " → iso8601 ["%Y/%m/%d %H:%M"] Z` (the rendered text is e.g. `2026/05/27 22:00 (UTC)`).
- `body_empty_acceptable: true` — the article detail body is also session-gated (POST `/api/ajax/pr_info_detail`).
  The current `article.content` selector (`main`) captures the SPA shell, which yielded ~2.9 kB of mixed shell+body
  in smoke; the body_empty_acceptable flag prevents future variability (e.g. consent re-prompt) from hard-failing
  validation. Bot consumers still get the row title, URL, and timestamp, which is the primary value for a news watcher.

## 회귀 검증

```text
schema OK
list 10
  807    2026-05-27T22:00:00+00:00  New Spotlight Pretty Derby and Spotlight Support Card Scouts
  100068 2026-05-26T03:30:00+00:00  Regarding Player Misconduct
  768    2026-05-25T22:00:00+00:00  Bonus Star Piece rewards in Career!
body chars 2953
```

`register.py --config` baseline = 10 entries.

## 일반화 후보 (deferred)

- POST-only JSON list endpoints whose standalone response is a sentinel ({"response_code": <N>} short body) → probe
  should mark `render_required` + "POST API session-bound". C-layer.
- `httpx_json` strategy: POST method support with optional empty body. F-layer. Not enough on its own for sites that
  also require a real browser session.

Both are appended to `docs/cases/_deferred_heuristics.md` for cross-site lift when a second sample lands.
