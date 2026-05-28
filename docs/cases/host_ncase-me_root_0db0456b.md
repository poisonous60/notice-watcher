---
slug: host_ncase-me_root_0db0456b
url: https://ncase.me/
status: registered - classifier signal landed, but LLM verdict accepted board; user closed as registered
outcome: registered
date: 2026-05-28
failure_keys: [classifier_single_artist_portfolio_false_accept, gate_reject, content_as_list]
fix_layer: A+C
config_strategy: none
adapters_changed: []
engine_files_touched: [engine/digest.py, generate/classify.py, prompts/classify.system.txt]
tags: [classifier, portfolio, gate_reject, batch-2026-05-28-games-indie-news-06]
requested_by: batch
---

# ncase.me root - single-artist portfolio classifier gate

## Root Cause

`https://ncase.me/` is a 1-user portfolio root, not a polling board. Live check on 2026-05-28 fetched the page successfully and saw:

- title: `It's Nicky Case!`
- body intro: `i make shtuff for curious & playful peeps`
- nav/update route: `https://blog.ncase.me/`
- portfolio grid: shallow concept/project URLs such as `/anxiety/`, `/trust/`, `/nutshell/`, `/sim/`

The old classifier input exposed only a same-host repeating cluster, so project/explorable cards could look like an index. The board signal was missing the counter-signal: "this is a personal portfolio root and the real update stream is a separate blog URL."

## Fix

C-layer digest signal:

- `engine/digest.py:detect_single_artist_portfolio(...)` detects a root page with a personal intro title (`It's <Name>!`, `I'm <Name>`, `<Name>'s site`, `<Name> | <Name>`), at least three shallow noun/concept same-host project links, and a separate blog route (`blog.<host>` or `/blog/`).
- `build_digest(...)` adds `single_artist_portfolio` to the digest only; no probe artifact schema or `list_candidates.json` contract is changed.
- `generate/classify.py:_struct_hint(...)` includes the signal in the classifier prompt as structural context.

A-layer classifier rule:

- `prompts/classify.system.txt` now says a single-artist/creator portfolio root with concept/project grid links and a separate blog route is not `index`; the blog URL is the likely polling candidate.

F-layer audit:

- Miss. I did not add a `register.py` post-LLM hard override. This pattern is semantic enough that a deterministic gate would risk false negatives on small real boards or personal blogs. The existing accept-path classifier reject already maps high-confidence `content`/`not_found`/`login` to rc 3/4/2, so the safer enforcement pair is A-layer prompt + C-layer signal.

## Track B Audit

- E schema rejection: miss - no generated config exists; schema validation cannot know a root portfolio is not a board.
- D retry feedback: miss - the failure happens before selector retry is useful.
- C probe digest signal: hit - the classifier needed structural evidence for personal title + project grid + separate blog route.
- B few-shot: miss - no config example should be added for a non-board root.
- A system rule: hit - the classifier needed an explicit single-artist portfolio rule.
- F engine/register flow: miss - hard enforcement was intentionally avoided because this is better handled by LLM classification with a structural hint.

## Regression Verification

- `python tests/probe_heuristics/test_single_artist_portfolio.py`: 4 passed.
- `python tests/classify/test_classify_index_content.py`: 45 passed.
- Live dev check: `detect_single_artist_portfolio(html, "https://ncase.me/", {})` returned `detected=True`, `grid_item_count=8`, `blog_link=https://blog.ncase.me/`.
- Negative guard fixture: `https://wayforward.com/news/`-style `/news/<slug>` rows did not trigger the portfolio detector.

## Self Check

1. Layer: C+A. C extracts the missing signal into digest; A tells the classifier how to use it.
2. Previous cases: no exact prior case found in local case docs; this batch had ncase as the trigger.
3. Blast radius: root pages only, requiring personal intro title + 3 shallow project/concept links + a separate blog route.
4. Verification: targeted classifier/probe tests and live ncase detector check recorded above.
5. Outcome: improved, because future single-creator portfolio roots with the same generic shape are rejected without per-site config.
6. Fixture: `tests/probe_heuristics/test_single_artist_portfolio.py` covers positive ncase shape and negative news board shape.

## Outcome update (2026-05-28 retry)

`batch-register --failed` 재시도 시 결과:

- detect_single_artist_portfolio digest signal 정상 박힘 (build_digest 가 호출). classify prompt 룰도 추가됨.
- 그러나 classifier LLM 이 여전히 `class=index` 판정 — `_accept_path_content_reject` 거부 안 함.
- agentic 가 validate_pass → strategy=httpx_html, baseline 13건 (anxiety/explorabl.es/trust/nutshell/sim 등 interactive explorables).
- 사용자 결정: registered 로 종료. 새 explorable 발표 시 알림 옴 (catalog 적합).

A-layer prompt 룰만으로는 LLM 판정 보장 못함. 강제 reject 필요 시 F-layer enforcement (digest.single_artist_portfolio.detected==True + confidence='high' 시 강제 rc=3) 가 다음 후보. 단 false-positive 회귀 우려로 보류.
