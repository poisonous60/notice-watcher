# Task — F-layer RSS-fallback override + date_only_to_iso slash + adriancourreges baseline

## Background

`notice-watcher` batch `2026-05-28-games-indie-news-05` drained: 4 gen_fail (rc=1) sites after default `auto` (api_loop_once → agentic codex). Cross-site pattern in 3/4: **all hybrid `site_kind` with validated RSS/Atom feeds, but LLM picks HTML strategy and gen_fails because the root URL is a landing page / forum-list / SPA shell, not the actual thread list**. 4th site has working HTML rows but a date-transform bug.

This task is an **agentic-position cross-site fix** per SKILL.md §0c-0: same fail signal in 2+ sites → fix once in F-layer / C-layer so future batches inherit it.

## Cohort

| slug | URL | last_feedback | site_kind | primary_feed (validated) |
|---|---|---|---|---|
| host_box2d-org_root_c360d996 | https://box2d.org/ | `probe_grounding_list_row_selector: item matched 0 nodes` | hybrid high | https://box2d.org/index.xml (rss, 22 items) |
| host_community-plays_root_dc9ef028 | https://community.playstarbound.com/ | `posts_nonempty 0건; probe_first_article mismatch` | hybrid med | https://community.playstarbound.com/forums/-/index.rss (rss, 6 items, site-wide) |
| host_randomascii-wor_root_f74fd8ea | https://randomascii.wordpress.com/ | `probe_grounding_list_row_selector: channel>item matched 0` | hybrid med | https://randomascii.wordpress.com/feed/ (rss, 10 items) |
| host_adriancourreges_root_3a1e3b11 | https://adriancourreges.com/ | `published_at_iso failed on slash dates` | hybrid med | https://adriancourreges.com/atom.xml (feed, 20 items) |

probe artifacts in `output/probe/<slug>/`. Failed configs in `output/poll_state/<slug>.FAILED.json`.

## Required fixes (you decide exact code shape — these are the gaps, not the prescription)

### Fix 1 — F-layer post-LLM RSS-fallback override (cross-site, primary)

**Where**: `scripts/register.py` — in the `GenerationError` catch path around line 3622-3650. After the existing `_generation_failure_reject_rc` post-mortem returns None (i.e., the failure is not a board-rejection), BEFORE `_save_failed` and `return 1`.

**What**: if `digest` has a **validated** RSS/Atom feed (`feed_candidates[*].validated == True` with `item_count >= 3`) AND `digest.site_kind.kind` ∈ {`rss`, `hybrid`}, attempt to build a minimal RSS/Atom `httpx_html` config from `primary_feed_url` and register it without LLM. If that config passes the same `register_with_config` flow (validation, baseline write), return 0 instead of rc=1.

A working RSS config has this shape (use `randomascii` /feed/ as the canonical example):

```json
{
  "version": 1,
  "site": "<host>",
  "board": "feed",
  "strategy": "httpx_html",
  "headers": {"Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"},
  "list": {
    "url_template": "<primary_feed_url>",
    "pagination": {"kind": "none"},
    "row_selector": "<channel > item OR feed > entry — pick from root_tag>",
    "fields": {
      "post_id": [{"from": "css", "selector": "guid, id", "text": true, "transform": [["strip"]]}],
      "title": [{"from": "css", "selector": "title", "text": true, "transform": [["collapse_ws"]]}],
      "url": [{"from": "css", "selector": "link", "text": true}],
      "published_at": [
        {"from": "css", "selector": "pubDate, published, updated", "text": true, "transform": [["iso8601"]]}
      ],
      "summary": [{"from": "css", "selector": "description, summary", "text": true, "transform": [["html_unescape"], ["collapse_ws"]]}]
    }
  },
  "article": {
    "fetch_kind": "html",
    "content": [{"from": "css", "selector": "div.entry-content, article, main", "html": true}],
    "body_empty_acceptable": true
  },
  "_source_url": "<primary_feed_url>",
  "_note": "F-layer RSS-fallback override — gen_fail after LLM HTML attempts; site_kind=hybrid|rss + validated feed."
}
```

For Atom feeds (`root_tag == 'feed'`), `link` is an `<link href="...">` attribute, not text — use `attr=href`. The helper must pick the right selectors based on feed type detected from `feed_candidates[*].root_tag`.

Pick selectors from the validated feed candidate's `root_tag` field. If `root_tag == 'rss'` use `channel > item` + text selectors; if `root_tag == 'feed'` (Atom) use `feed > entry` + `link[href]` attr selector + `id` + `updated` instead of `pubDate`.

**Implementation suggestion**: factor out a `_build_rss_fallback_config(digest, url) -> Optional[dict]` helper, then call `register_with_config(cfg, ...)` or the same internal flow `_save_state` uses to finalize. If the RSS config fails validation too, fall through to the original `_save_failed` path unchanged.

**Test**: re-run `python scripts/register.py --reuse-probe "https://box2d.org/"` and the other 3 URLs from this cohort. Expect 3/4 to register as RSS (box2d, community.playstarbound, randomascii). adriancourreges should still gen_fail without Fix 2.

**Side-effects to check**: this override only fires after retries are exhausted, so it shouldn't change any currently-passing path. But verify `probe_smoke.py --stage 3 --stage 5` still passes — particularly that no existing case expects `rc=1` on a hybrid+RSS site (search `git log -- docs/cases/` for any case that expects gen_fail outcome on a hybrid+RSS site).

### Fix 2 — `date_only_to_iso` accept slash dates

**Where**: `engine/transforms.py:123` `_date_only_to_iso`.

**What**: normalize `/` → `-` in the input before formatting, so `2018/12/02` and `2018-12-02` both produce `2018-12-02T00:00:00<tz>`. Slash dates are a common natural URL format (`/blog/YYYY/MM/DD/slug/`), and LLM-generated configs often produce them via `regex_extract` from URL paths without inserting an extra `replace`.

Add a one-line normalization. Add a corresponding test in `tests/` if the existing transform tests are structured per-function.

**Test**: re-run `python scripts/register.py --reuse-probe "https://adriancourreges.com/"`. Expect rc=0 (registered as HTML with `projectThumbnail` rows).

### Fix 3 — adriancourreges live URL is `www.adriancourreges.com`

The catalog entry is `https://adriancourreges.com/` which 301-redirects to `http://www.adriancourreges.com/`. The probe captured the redirected page so probe artifact is correct, but if Fix 2 alone is not enough, also accept that the working URL is `www.`. Don't add per-site config — verify whether redirect is being followed by `register.py` correctly (it usually is).

## Out of scope

- Per-site `configs/<slug>.json` files (Track A) — avoid unless Fix 1 + Fix 2 don't recover at least 3/4 sites.
- Modifying the prompt (already covers RSS dispatch — it's the LLM that didn't comply, F-layer override is the right hammer).
- Touching gate logic (board_shape_check / classifier).
- Touching anything outside `scripts/register.py`, `engine/transforms.py`, and any required helper file.

## Acceptance (you self-check before STOP)

1. `python scripts/probe_smoke.py --stage 3 --stage 5` PASS (no regressions).
2. `python scripts/register.py --reuse-probe "https://box2d.org/"` → rc=0, config written to `configs/host_box2d-org_root_c360d996.json` with `strategy=httpx_html` + `list.url_template=https://box2d.org/index.xml` + RSS selectors.
3. Same for `https://community.playstarbound.com/`, `https://randomascii.wordpress.com/`, `https://adriancourreges.com/`.
4. Write a case file `docs/cases/_generic_rss_fallback_override.md` documenting Fix 1 (mechanism: improved, fix_layer: F+C if date also). For adriancourreges, write `docs/cases/host_adriancourreges_root_3a1e3b11.md` (improved if Fix 2 alone recovered it, handcrafted if also needed config tweaks).
5. **STOP before commit/push/deploy**. Claude does diff review + merge + N100 deploy.

## Reference

- SKILL.md §0c (codex delegate mode), §0c-0 (cross-site agentic-first), §2c (probe heuristic), §6 (fix-layer 6 자리)
- ADR 0007 (classifier veto layer — don't touch)
- ADR 0008 (codex delegation)
- `prompts/config_writer.system.txt` lines 29-33, 132 (existing RSS dispatch logic — already comprehensive; F-layer is the enforce mechanism)
