---
slug: host_afkjourney-farl_news_2382ee85
url: https://afkjourney.farlightgames.com/news/
status: ✅ improved
outcome: improved
date: 2026-05-27
fix_layer: F
failure_keys: [var_news_list_inline_js, orb_blocked_hydration_cdn, posts_nonempty_zero]
config_strategy: playwright_html
engine_files_touched: [engine/strategies/playwright_html.py]
adapters_changed: []
tags: [engine-orb-bypass, lilith-cdn, farlight, vue-hydration]
requested_by: user
vocab_candidates: []
---

# AFK Journey /news/ — ORB-blocked hydration CDN

## root cause

AFK Journey serves a real news board at `https://afkjourney.farlightgames.com/news/`. The static HTML contains one Vue
template and a large inline `var news_list = '{...}'` payload, but the actual row DOM is populated only after the page's
Vue script runs.

The page loads `https://dapcdn.63cj.com/common-utils/index.1.1.7.umd.js` before the inline script that calls
`reportH5SlsEvent`. The CDN response has `Content-Type: text/html` for a `.js` URL, which Chrome blocks as ORB in the
normal case. In the current dev-box run, the CDN also returned a Tencent challenge HTML body for that JS URL; header
rewrite alone fixes ORB, and the optional `fallback_body_when_html` no-ops this analytics dependency when the response
body is actually HTML. With that, the page proceeds to load `/static/js/afkjourney/en/pc/news_list.js` and hydrates
`a.news_item[href]` rows.

## Track B 6-layer audit

- **E** schema 거부: miss — config shape is valid; no invalid selector or transform to reject.
- **D** retry feedback: miss — failure is browser-level script blocking before selectors run, not retry feedback from
  generated config validation.
- **C** probe digest 신호: miss for this patch — probe could flag `var <name>_list` inline payload plus ORB-blocked CDN
  script as a render-risk signal, but `probe/` changes are out of this task scope. Deferred candidate appended.
- **B** few-shot: miss — no example can make Chromium ignore ORB or a challenge HTML body.
- **A** system rule: miss — prompting cannot provide a browser route hook that the engine lacks.
- **F** engine code: hit — `playwright_html` now supports config-driven route response header rewrites for CDN JS
  MIME mismatches, with an optional HTML-body fallback for analytics scripts that are nonessential to extraction.

## fix

`engine/strategies/playwright_html.py` adds `route_rewrite_response_headers`:

```json
{
  "url_pattern": "https://dapcdn.63cj.com/**/*.js",
  "headers": {"content-type": "application/javascript"}
}
```

Each entry registers `context.route(url_pattern, handler)`. The handler fetches the original response, merges headers
case-insensitively, and fulfills the route with the original response plus rewritten headers. When a route entry also
sets `fallback_body_when_html`, the handler uses that fallback only for `.js` URLs whose original response is HTML and
whose rewritten content type is JavaScript.

`configs/host_afkjourney-farl_news_2382ee85.json` uses the new route hook, `wait_selector: a.news_item[href]`,
`row_selector: div.news_list > a.news_item`, `post_id` from `/news/([0-9a-f]{32})/`, title from `.title_box`, URL from
the hydrated `href`, and article content from `div.news_content`.

## 회귀 검증

- `python -m pytest tests/probe_heuristics/test_playwright_route_rewrite_headers.py` → PASS.
- AFK live adapter, repo default page size:

  ```text
  list 10
    e10fe489080baa333e03ce2a5a7fa34c '5/7(목) 버전 업데이트 알림 (버전 1.6.4)'
    f375ca37e0b1cb64a35d66492907935e '4/9(목) 버전 업데이트 알림 (버전 1.6.3)'
    d1042fb9700350aabbc11ae0d4b0148a '<AFK: 새로운 여정> 확률 안내 (3월 25일 업데이트)'
  body chars 3135
  ```

- AFK live adapter with `page_size=30` → `list 19`, matching the full hydrated row count expected in the task brief.

## ship evidence

Current handoff explicitly requested: `Task: engine F-layer + playwright_html route_rewrite config option for ORB bypass`
for `https://afkjourney.farlightgames.com/news/`, including the exact slug
`host_afkjourney-farl_news_2382ee85` and required selectors. This is direct slug/URL ship evidence from the user.

## 일반화 후보

`var <name>_list` inline payload plus a cross-origin `.js` script blocked by ORB is a probe-digest signal candidate.
This patch intentionally leaves `probe/extract.py` untouched per scope and records the C-layer idea in
`docs/cases/_deferred_heuristics.md`.
