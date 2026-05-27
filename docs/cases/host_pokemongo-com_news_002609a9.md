---
slug: host_pokemongo-com_news_002609a9
url: https://pokemongo.com/news/
status: ✅ handcrafted
outcome: handcrafted
date: 2026-05-28
fix_layer: none
failure_keys: [css_module_hashed_class, unescaped_tailwind_colon, posts_nonempty_zero]
config_strategy: httpx_html
engine_files_touched: []
adapters_changed: []
tags: [css-modules, hashed-classes, niantic, svelte, batch-2026-05-28-games-gacha-global-02]
requested_by: user
vocab_candidates: []
---

# pokemongo.com /news/ — CSS-module hashed classes break literal selectors

## root cause

Niantic web for Pokémon GO ships a Svelte build whose CSS module class names carry a build-hash suffix
(`_newsCards_1stmd_22`, `_newsCard_1stmd_22`, `_newsCardContent_1stmd_65`, `_size:heading_ovqdr_19`). Two failure modes hit
the autogen path:

1. The probe heuristic recorded a literal selector with an unescaped colon (`._size:heading_ovqdr_19`). soupsieve treats
   the `:` as a pseudo-class introducer and rejects compile (`Pseudo-class ':heading_ovqdr_19' is not implemented`).
2. Even after the agentic loop trimmed the bad colon segment, it kept the build-hash class literals
   (`._newsCards_1stmd_22 > a._newsCard_1stmd_22`). Those hashes rotate on every deploy, so the selector that the LLM
   "validated" against the captured probe HTML becomes empty against the live page once Niantic redeploys (and the
   live page that `register.py` re-fetches at validation time already had a fresher build than the cached probe).

Net effect: `posts_nonempty 0` despite the static HTML carrying 30 article cards.

## Track B 6-layer audit

- **E** schema 거부: miss — config shape is valid; the bad selector only fails inside soupsieve at fetch_list time, not
  in `engine/config_schema.py:validate_config`.
- **D** retry feedback: miss — register already surfaces "Pseudo-class … is not implemented" in the retry feedback;
  the agentic loop did read it, dropped the colon segment, but kept the volatile hash literals and ran out of cycles.
- **C** probe digest 신호: miss for this patch — the deferred candidate is "rewrite hashed CSS-module class fragments
  to `[class*="<stable-prefix>"]` attr-contains form in `probe/extract.py` row patterns". Out of scope for a single
  manual config; recorded for cross-site lift once a second sample hits the queue.
- **B** few-shot: miss — adding one more example would not teach the agentic loop the "prefer attr-contains for hashed
  classes" rule reliably; it is a structural rewrite, not a shape to copy.
- **A** system rule: miss for this patch — a one-line "prefer `[class*="_prefix_"]` when class fragment ends in a
  build-hash" rule is a candidate, but writing it now without a second corroborating site risks a noisy prompt change.
- **F** engine code: miss — the engine already understands attr-contains selectors; no new code needed.

All six layers miss → §2 강제 인용 4b (a) satisfied.

## ship evidence

User instruction this turn: `차단된거나 게이트 거부 당한 건 신경쓰지 말고 gen_fail 된 것만 사이트 파악하고 처리해줘. … 일반화 시도해보고 정 안되면 수동 config라도 짜보던가.` followed by `/goal 우선 말해두자면 셋 다 게시판이기는 해. 일반화로 해결할 수 있으면 좋을 것 같지만, 안 되겠으면 수동 config라도 지원해줘.` Pokémon GO news is one of the three gen_fail slugs the user explicitly named for ship via manual config when generalization is not on the table this PR. §2 강제 인용 4b (b) satisfied.

## fix

`configs/host_pokemongo-com_news_002609a9.json`:

- `strategy: httpx_html` — diagnosis verdict is "정적 HTTP로 충분"; the static HTML carries the 30 cards.
- `row_selector: div[class*="_newsCards_"] a[class*="_newsCard_"]` — attr-contains pins the stable prefix and ignores
  the rotating build-hash suffix, so the selector survives Niantic redeploys.
- `title` from `div[class*="_newsCardContent_"]` (same attr-contains rationale; the heading text is duplicated in the
  content card body anyway).
- `published_at` from `<pg-date-format timestamp="…">` with `unixtime_to_iso "Z" "ms"` (timestamps are unix epoch ms).
- `article.content` from `article` (the article page is a clean static doc, `<article>` already wraps the body).

## 회귀 검증

```text
schema OK
list 30
  go-pass-june-2026 'The Timed Incubator returns in GO Pass: June!' 2026-05-27T16:58:00+00:00
  communityday-june-2026-frigibax 'Frigibax will be featured in June Community Day, and Communi' 2026-05-26T16:58:00+00:00
  go-battle-league-forever-forward 'GO Battle League: Forever Forward Update' 2026-05-26T13:00:00+00:00
body chars 11459
```

`register.py --config` baseline = 30 entries.

## 일반화 후보 (deferred)

Pattern: a probe row pattern whose class name fragment ends with a short alphanumeric build-hash
(`_<word>_<hash>` form, e.g. `_newsCards_1stmd_22`) should be rewritten by `probe/extract.py` to the attr-contains form
`[class*="_<word>_"]` before being handed to the LLM. The LLM then has no way to "validate against a stale hash". Single
sample today; appended to `docs/cases/_deferred_heuristics.md` to wait for a second hit before lifting into a real
C-layer heuristic (CLAUDE.md §8a — escalate only on cross-site recurrence).
