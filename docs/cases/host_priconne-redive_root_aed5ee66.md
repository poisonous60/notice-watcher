---
slug: host_priconne-redive_root_aed5ee66
url: https://priconne-redive.jp/
status: ✅ improved
outcome: improved
date: 2026-05-28
fix_layer: none
failure_keys: [wordpress_rest_404, llm_picked_wrong_row_selector, posts_nonempty_zero]
config_strategy: httpx_html
engine_files_touched: []
adapters_changed: []
tags: [wordpress, agentic-recovery, batch-2026-05-28-games-gacha-global-02]
requested_by: user
vocab_candidates: []
---

# priconne-redive.jp / — agentic recovery on rerun

## root cause

`https://priconne-redive.jp/` advertises a WordPress REST endpoint (`Link: <https://priconne-redive.jp/wp-json/>; rel="https://api.w.org/"`), but the `wp-json/wp/v2/posts` endpoint returns 404 — the site is WordPress-themed for layout, not blog-API enabled. The original autogen run picked the 4th probe row candidate (`div.news-list-wrapper > div`, count 0 against the rendered DOM) instead of the strongest one (`ul.news-list > li`, count 10), so fetch_list returned 0 posts.

## what actually fixed it

Plain `register.py --reuse-probe "https://priconne-redive.jp/"` succeeded this turn — the api_loop_once attempt still failed with `posts_nonempty 0`, but the agentic escalation produced a passing config in 52.6 s (one cycle, validate_pass). The resulting config uses `row_selector: "#cat-news ul.news-list > li"` (a stricter scope than the bare `ul.news-list > li` probe hint), `row_required_selector: "dd > a[href*='/news/']"` to drop sticky/decoration rows, and `regex_extract "/news/[^/]+/(\d+)/"` to pull the numeric post_id out of paths like `/news/event/36418/`.

Nothing in this PR's diff actually fixed priconne — the agentic loop landed on the right config on its own. This case
is `improved` because the recovery came through generic agentic + WordPress fallback path (`register.py:_wordpress_detect` correctly fell back when wp/v2/posts 404'd), not via a handwritten config.

## Track B 6-layer audit

- **E** schema 거부: miss — agentic config validated cleanly.
- **D** retry feedback: miss — `posts_nonempty 0` feedback was enough for agentic to pick the right row selector on
  one cycle.
- **C** probe digest 신호: miss — probe had already surfaced both row candidates with the right one ranked first.
- **B** few-shot: miss — no example was added in this turn.
- **A** system rule: miss — no prompt change in this turn.
- **F** engine code: miss — the WordPress detect/fallback already covered this site shape.

All six layers miss → §2 강제 인용 4b (a) satisfied. Track A skipped — no handcraft needed.

## ship evidence

User instruction this turn: `차단된거나 게이트 거부 당한 건 신경쓰지 말고 gen_fail 된 것만 사이트 파악하고 처리해줘.` priconne-redive.jp was one of the three gen_fail slugs in the 2026-05-28-games-gacha-global-02 batch.

## 회귀 검증

```text
[register] ✅ 등록 완료
  config: configs/host_priconne-redive_root_aed5ee66.json  (strategy=httpx_html, site=priconne-redive.jp, board=news)
  state : output/poll_state/host_priconne-redive_root_aed5ee66.json  (baseline 10건 — 이 글들은 '새 글' 아님)
    36418  2026-05-27  ストーリーイベント「Re:birth maiden ‐再誕の乙女たち‐」開催決定！
    36442  2026-05-27  Ver.12.3.6アップデートのお知らせ
    36435  2026-05-26  「5月クランバトル」開催中！
```
