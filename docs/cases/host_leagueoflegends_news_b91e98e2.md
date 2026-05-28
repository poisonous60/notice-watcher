---
slug: host_leagueoflegends_news_b91e98e2
url: https://leagueoflegends.com/news/
status: "✅ improved — article cards outrank SVG decoration in probe row candidates"
outcome: improved
date: 2026-05-28
fix_layer: C
failure_keys: [posts_nonempty, probe_grounding_list_row_selector]
config_strategy: auto
engine_files_touched: [probe/extract.py]
tags: [cross-site, locale-redirect, row-scoring, riot]
---

## 무엇이 일어났나

`https://leagueoflegends.com/news/` 는 `www.leagueoflegends.com/ko-kr/news/` 로 redirect 되고 static SSR에 article href가 충분히 있다. 하지만 `html_repeating_patterns` 정렬이 `child_count` 만 보면서 `g > path` SVG decoration(`child_count=15`, `first_text=""`, `sample_url=None`)을 실제 card row(`child_count=12`, text+article href 있음)보다 앞세울 수 있었다.

실제 fail signal:
- `[FAIL] posts_nonempty 0건`
- `probe_grounding_list_row_selector 0 nodes`

## 픽스

`probe/extract.py:html_repeating_patterns` 정렬에 row evidence quality penalty를 추가했다. `sample_url` 없음, `first_text` 없음, SVG/shape tag는 감점하고, 같은 품질 bucket 안에서는 `child_count` 내림차순을 유지한다.

## 6-layer audit

- E schema: miss — selector가 schema상 유효해도 row 후보 순위가 나쁘면 못 잡는다.
- D retry feedback: miss — 실행 실패 뒤 selector feedback으로는 probe top candidate 오염을 일반화하기 어렵다.
- C probe heuristic: hit — row scoring이 실제 article evidence를 우선하도록 바뀌었다.
- B few-shot: miss — Riot 전용 예제 없이도 generic row evidence 정렬로 풀어야 한다.
- A system prompt: miss — LLM 지시가 아니라 후보 ranking 문제다.
- F engine/recognizer: deferred — Riot Nuxt game site recognizer 후보는 별도 coverage 작업으로 남긴다.

## 회귀 검증

- `tests/probe_heuristics/test_html_repeating_patterns.py`
  - `g > path` 15개와 article card 12개 fixture가 수정 전 실패, 수정 후 article card를 top candidate로 반환.
- `python scripts/probe_smoke.py --stage 3 --stage 5` → exit 0, `PASS 1790 FAIL 0 WARN 1 SKIP 0`.

## probe artifact 확인

`output/probe/host_leagueoflegends_news_b91e98e2/` 는 이 worktree에 없어 artifact replay는 수행하지 못했다. fixture가 동일 failure mode를 고정한다.

## deferred

`data-testid="card"` / `card-title` / `card-date` / `category` 기반 Riot Nuxt news template은 League of Legends, Wild Rift, Valorant, TFT, Legends of Runeterra 계열 F-layer recognizer 후보로 남긴다. 이번 변경은 generic C-layer row scoring만 다룬다.
