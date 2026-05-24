---
slug: host_capitalgroup-co_advisor_cc24afab
url: https://www.capitalgroup.com/advisor/insights.html
board: insights
status: fixed
date: 2026-05-24
outcome: handcrafted
fix_layer: config
failure_keys:
  - posts_nonempty
  - static_variant_rows_not_promoted
  - auth_redirect_article
---

# Capital Group advisor insights

## Root Cause

`register.py` generated a `playwright_html` config against `/advisor/insights/articles.html`, but the working article rows are on the original `/advisor/insights.html` page after the browser/Akamai flow. The probe digest only surfaced script containers from the static variant, while `s1.Hcap.html` contained the real `/advisor/insights/articles/*.html` links.

Articles redirect unauthenticated direct fetches through `/advisor/public/authentication-0.htm`, so the fix keeps this as a list-only config with `body_empty_acceptable`.

## Evidence

- preflight: miss -- no existing config/recognizer and no prompt/engine/probe commits after `2026-05-24T03:06:22.854374+00:00`.
- last feedback: `[FAIL] posts_nonempty: 0건`.
- diagnosis verdict: `정적 HTTP로 충분`; list digest had `first_article_url: None`.
- matching failure catalog: `docs/config 자동생성 실패 케이스.md` §2a, list extraction failure.
- cross-check: `posts_nonempty` has prior cases and Track B trigger; deferred `static_variant_rows_not_promoted` also triggers. This case records that signal, but no generic probe change was made because promoting headless variant rows changes probe contract behavior beyond this single slug.

## Fix

Added `configs/host_capitalgroup-co_advisor_cc24afab.json`:

- strategy: `playwright_html`
- list URL: `https://www.capitalgroup.com/advisor/insights.html`
- rows: text article links plus featured card wrappers with `data-href`
- article mode: list-only (`body_empty_acceptable: true`)

## Verification

- Schema validation: pass.
- `make_adapter` list smoke: 5 posts, non-empty titles and URLs.
- `register.py --config configs/host_capitalgroup-co_advisor_cc24afab.json`: pass, baseline 5 posts.
- `probe_smoke.py --stage 3 --stage 5`: pass (`1170 PASS, 0 FAIL`).
