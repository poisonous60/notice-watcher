---
slug: _chunk-post-preflight-no-first-gate
url: https://www.hypergryph.com/
status: agentic self-veto rc=3 pattern now blocked pre-generate (LLM 0 cost)
outcome: improved
date: 2026-05-26
fix_layer: F+A
failure_keys: [gate_reject, agent_self_veto_non_board, agentic_quota_waste, rss_only_over_confidence]
config_strategy: none
adapters_changed: []
engine_files_touched: [scripts/register.py, prompts/classify.system.txt, bot/fail_taxonomy.py, tests/fail_taxonomy/test_classify_fail.py]
tags: [gate, classifier, quota, batch-2026-05-26-games-cn]
---

## What Happened

2026-05-26 games-cn batch (100 sites, mostly Chinese game studio homepages) returned
53 rc=3 gate_reject. Sub-classification:

- 22 / 53 (41%) = **`agent_self_veto(non_board)` pattern**:
  - `_board_shape_check` would reject (same-host signals 0).
  - LLM classifier veto-overrode to `index` (conf ≥0.5) based on RSS/Atom feed candidates.
  - `_preflight` then could not find `first_article_url` (no detail page to render).
  - Generate phase invoked agentic; agent inspected same digest and self-vetoed `non_board`
    after ~11–22s (codex cli wall time × 22 sites ≈ 6 minutes wasted quota).
- Remaining 31 / 53 = legitimate `accept_path` classifier veto (catalog/content conf ≥0.7)
  or other early gate hits — those already cheap (no agentic call).

Sample failing slugs (NO_FIRST): `host_ieg-tencent-com_root_d9a487e5`,
`host_pvp-qq-com_root_596f232a`, `host_lol-qq-com_root_c05b9bd7`,
`host_yys-163-com_root_85086bfc`, `host_mihoyo-com_news_15f8ea6a`,
`host_ys-mihoyo-com_root_28ea4870`, `host_zzz-mihoyo-com_news_6e043194`,
`host_hypergryph-com_root_0abc5e11`, `host_37games-com_root_dfebdb88`, ... (22 total).

## Root Cause

Two separate weaknesses combined to leak this pattern to agentic:

1. **F-layer** — no gate between `_preflight` and generate enforced "did preflight find
   *any* same-host article anchor?". `_board_shape_check` ran *before* preflight and
   could be classifier-overridden by RSS feed alone, so the pipeline reached generate even
   when `first_article_url is None` and same-host repeating clusters were 0.
2. **A-layer** — `prompts/classify.system.txt` rule line 13 (`RSS/Atom 피드가 있으면 index
   가능성이 높다`) led the classifier to over-confidently `index`-vote on company
   homepages that expose marketing RSS without an actual board page.

## Fix

### F-layer — `scripts/register.py`

Added `_no_first_post_preflight_check(digest, url)` (function near `_board_shape_check`)
and a call site after `_preflight` and before the generate phase. Conditions (all four
required to reject):

- `first_article_url` is None or not same-host
- `article_sample.clicked_resolved_url` is None / not same-host / anti-bot redirect
- `list_candidates.html_repeating_patterns` has zero same-host entries
- `traffic_json_api_candidates`, `inline_js_data_candidates`,
  `hydration_list_candidates` are all empty

On match → `_save_rejected` with `note="gate: post_preflight_no_first"` + `learn=False`
(page-specific, do not blacklist host) + return `rc=3`. The function returns early
(`return True, ""`) before any `_count_board_feed_signals` invocation when first_article or
JSON/inline/hydration signals exist, so legitimate sites with extractable structure are
untouched.

`--gate-only` mode skips the new check (preserves the LLM-zero-call contract used by
`post-fix-cleanup`).

### A-layer — `prompts/classify.system.txt`

Added rule:

> **RSS 단독 신호로 index 판단 금지**: probe 가 같은-호스트 반복 글-링크 행을 *0종*
> 보고했고 첫 글 URL 도 못 잡았는데 *RSS/Atom 피드 후보만* 있으면 index 로 기울지 말고
> 본문/링크 구조를 본다. 회사 홈/제품 랜딩/카탈로그 페이지가 마케팅용 RSS 를 노출하는
> 경우가 흔하다(게임회사 홈, 제품 소개 사이트 등). 본문이 회사·게임·제품 소개 문구
> 중심이면 catalog 또는 content 다 — RSS 가 있어도 게시판이 아니다. 진짜 게시판이면
> RSS 외에 *정적 HTML 에도* 글-링크 cluster 가 ≥1종 보인다.

Together with the F-layer gate this gives two independent defenses: the prompt nudges the
classifier to *not* veto-override on RSS alone, and even if it does, the post-preflight
gate catches the leak before agentic.

### Taxonomy

`bot/fail_taxonomy.py` — new `Subkind("post_preflight_no_first", …)` added to the
`gate_reject` family, placed *before* `classifier_reject` so its specific
`"post-preflight NO_FIRST"` token wins over the generic `"분류기"` matcher. Matching
test added in `tests/fail_taxonomy/test_classify_fail.py`. `docs/fail 분류.md`
regenerated via `scripts/gen_fail_taxonomy_doc.py`.

## Verification

- `probe_smoke.py --stage 3 --stage 5` — PASS 1491 / FAIL 0.
- `tests/fail_taxonomy/test_classify_fail.py` — 58/58 PASS (new case included).
- `python -c "..."` with `engine.digest.build_digest(...)`:
  - `host_hypergryph-com_root_0abc5e11` (NO_FIRST sample) — gate fires correctly.
  - `host_ak-hypergryph-c_news_33846550` (`first_article=/#index` same-host) — gate
    passes (no false positive).
- codex companion review — PASS (no violations).
- Pre-push hook (probe_smoke) — PASS.
- N100 deploy — fast-forward `e6538fb..0a6b9da`, `notice-bot.service` restarted.
- batch-register `--catalog=2026-05-24-games-cn --failed` (18 entries, post-deploy):
  - 1 done (snail.com/news — Phase 2 skip restored agentic wall budget).
  - 13 rc=4 reclassified as `verdict='TARGET_NOT_FOUND'` (`/news/` paths were 404).
  - 3 rc=5 cap_blocked (37.com, kurogames, infoldgames — anti-bot).
  - 1 rc=3 ak-hypergryph/news — `first_article='/#index'` so NO_FIRST gate passes;
    agent self-veto remains. SPA-fragment-only pattern is a separate weakness (see
    Deferred Heuristics).

NO_FIRST gate direct measurement deferred: the failed-retry pass did not re-run the 22
matching slugs because their `.REJECTED` markers are still on disk. Next fresh batch
or explicit `.REJECTED` purge will show the live save (~22 sites × ~17s agentic per ≈
6 minutes codex quota recovered).

## Impact

- 22 / 53 (41%) of games-cn rc=3 will skip agentic on next observation of the pattern.
- Pattern is generic — applies to any marketing landing / catalog hub that exposes
  RSS without a real board.
- gen_fail recovered for 1 / 2 cases (snail), confirming the Phase 2 skip win
  (commit `e6538fb`) was the right infra direction. The remaining gen_fail
  (ak-hypergryph) is now agent self-veto rc=3 (correctly classified, no more wall-budget
  starvation).

## Deferred Heuristics

SPA-fragment-only board detector — when every `html_repeating_patterns[*].href_pattern_guess`
is the same SPA fragment (e.g. `/#index`) and same-host but never points to a distinct
article URL, treat as not-a-board (currently `fau_same=True` passes through the new gate
and reaches agent self-veto). Trigger: 2+ sites in one batch exhibit this; not enough
evidence yet.

## Related

- ADR 0007 — LLM index/content classifier veto layer.
- `_chunk-hub-gate-rss-escape.md` — validated RSS feed escape in heterogeneous_hub gate
  (different direction: rescue real boards; this case prevents false-rescue of non-boards).
- commit `0a6b9da` — engine fix + classifier prompt + taxonomy.
- commit `e6538fb` — Phase 2 HAR skip + daemon-reuse-off (enabled the snail gen_fail
  recovery via wall-budget headroom).
