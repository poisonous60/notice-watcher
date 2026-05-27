---
slug: host_community-king-_news_f9079edd
url: https://community.king.com/news/
status: 🚫 REJECTED + park-gate-fail (Vanilla Forums community directory)
outcome: rejected
date: 2026-05-27
failure_keys: [gen_fail, gate_fail_park, vanilla_forums, locale_redirect, forum_directory]
fix_layer: none
config_strategy: n/a
adapters_changed: []
engine_files_touched: []
tags: [games-mobile-batch, king, vanilla-forums, community-directory, classifier-fallthrough]
requested_by: 2026-05-24-games-mobile-batch-retry
---

## 조사 결과

probe `list_candidates.json`:
- 첫 글 = `https://community.king.com/en/blossom-blast-saga` (forum board, 게시판 카테고리)
- JSON API 후보 = `https://community.king.com/en/api/v2/subcommunities?expand=all`

live curl:
- `/news/` → **302 Found → location: https://community.king.com/en/** (community home, *not* `/en/news/`)
- `/en/api/v2/subcommunities?expand=all` → JSON `[{subcommunityID: 51, name: "Candy Crush Saga", folder: "candy-crush-saga", url: "/en/candy-crush-saga", layoutViewType: "discussionList"}, ...]`

= **Vanilla Forums platform**. `/news/` 는 community home 으로 redirect 되고, 그 home 은 *각 게임 = subcommunity = forum board* directory. **news 게시판 아님 — community forum index**.

batch retry: probe 가 forum board catalog 의 게임 카드를 row 로 잡았으나 LLM 이 `probe_grounding_list_row_selector: ul > li matched 0` hard fail → agentic max_cycles fail → `.FAILED.json`.

## 처리

- dev `triage_gate_failed.json` 박힘 (`park-gate-fail` — 분류기 개선 후 sweep 가능)
- dev + N100 `.REJECTED.json` 박힘 (봇 응답 'rejected' 일관, CLAUDE.md §8c 의 종료 자리 의무)
- jobs row latest status='rejected' update
- 종료 자리 = park-gate-fail + REJECTED 손-박기 (분류기 fallthrough — community forum directory)

## 후보 (deferred)

`_deferred_heuristics.md` 의 `vanilla_forums_subcommunity_directory_detect` — `community.<name>.com/<locale>/api/v2/subcommunities` API + locale redirect (`/<path>` → `/<locale>/`) → forum/community directory 분류기 신호 (게시판 아님). catalog 1건이라 보류.
