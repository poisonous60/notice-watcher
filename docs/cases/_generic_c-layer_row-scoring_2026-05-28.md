---
slug: _generic_c-layer_row-scoring_2026-05-28
url: N/A
status: "✅ improved — C-layer row evidence scoring and static-vs-SPA grounding"
outcome: improved
date: 2026-05-28
fix_layer: C
failure_keys: [probe_grounding_list_row_selector, fetch_list_0_url_mismatch, posts_nonempty]
config_strategy: auto
engine_files_touched: [probe/extract.py, probe/diagnose.py]
tags: [cross-site, spa, locale-redirect, row-scoring, static-evidence]
---

## 무엇이 일어났나

Batch `2026-05-28-games-online-live-service-02` 의 gen_fail 2건이 같은 C-layer 약점을 보였다.

| slug | 신호 | 원인 |
|---|---|---|
| `host_pubg-com_news_17f4ebc1` | static placeholder row 17개, rendered article URL 존재, runtime `fetch_list 0` | `_static_row_evidence` 가 rendered `first_article_url` fallback을 static evidence로 오인 |
| `host_leagueoflegends_news_b91e98e2` | static SSR article href 107개, probe top row가 `g > path` | `html_repeating_patterns` 가 `child_count` 만 보고 SVG decoration을 article card보다 앞세움 |

이 문제는 selector 손수정이 아니라 probe digest 품질 문제다. LLM/agentic은 probe 후보를 신뢰하므로, row 후보와 static evidence가 실제 article href/text를 담는지 C-layer에서 보장해야 한다.

## 무엇을 바꿨나

- `probe/extract.py:html_repeating_patterns`
  - 정렬에 row evidence penalty를 추가했다.
  - `sample_url` 없음, `first_text` 없음, SVG/shape tag(`svg`, `g`, `path`, `circle`, `rect`, `polygon`, `use`, `defs`)를 감점한다.
  - 같은 품질 bucket 안에서는 `child_count` 우선 정렬을 유지한다.
- `probe/diagnose.py:_static_row_evidence`
  - `list_payload.first_article_url` fallback을 static evidence로 쓰지 않는다.
  - static-like result의 `body_path` HTML에서 pattern selector를 직접 select하고, 해당 static node 안의 non-JS article href를 찾아야 evidence로 인정한다.
  - static body에 href가 없으면 `static_row_evidence=None` 이 되어 `static_vs_headless_check` 의 SPA/hydration 판단이 살아난다.

## 6-layer audit

- E schema: miss — config schema 단계에서 알 수 없는 probe digest 품질 문제다.
- D retry feedback: miss — 실행 실패 feedback 전에 probe가 잘못된 evidence를 제공한다.
- C probe heuristic: hit — row 후보 정렬과 static-vs-headless evidence acceptance를 고쳤다.
- B few-shot: miss — 사이트별 selector 예시를 늘려도 rendered/static evidence 오염은 남는다.
- A system prompt: miss — LLM 지시가 아니라 입력 digest의 후보 순위/근거 문제다.
- F engine/recognizer: deferred — Riot 계열 recognizer 후보는 별도 플랫폼 coverage로 볼 수 있으나, 이번 PR 범위는 generic C-layer다.

## 회귀 검증

- RED 확인: `python scripts/probe_smoke.py --stage 5` 가 새 fixture 2건에서 실패했다.
  - `test_html_repeating_patterns:article_rows_outrank_svg_decoration`
  - `test_static_row_evidence:rejects_rendered_sample_url_without_static_href`
- GREEN 확인: `python scripts/probe_smoke.py --stage 5` → exit 0, `142 파일 · 1483 케이스 · 0 FAIL · coverage 49/49`.
- 최종 확인: `python scripts/probe_smoke.py --stage 3 --stage 5` → exit 0, `PASS 1790 FAIL 0 WARN 1 SKIP 0`.

## probe artifact 확인

요청된 replay artifact 경로를 확인했지만 이 worktree에는 없었다.

- `output/probe/host_pubg-com_news_17f4ebc1/` 없음
- `output/probe/host_leagueoflegends_news_b91e98e2/` 없음

따라서 실제 artifact replay verdict 비교는 수행하지 못했다. 대신 두 회귀를 fixture로 고정했다.

## deferred

Riot Nuxt game news template (`data-testid=card`, `card-title`, `card-date`, `category`)는 League of Legends / Wild Rift / Valorant / TFT / Legends of Runeterra 계열 recognizer 후보로 보인다. 이번 변경은 C-layer generic row evidence 보정만 하며, F-layer recognizer는 별도 PR 후보로 남긴다.

`docs/cases/INDEX.md` 와 `output/cases.sqlite3` 는 이 Codex handoff의 hard-stop 지시에 따라 갱신하지 않았다.
