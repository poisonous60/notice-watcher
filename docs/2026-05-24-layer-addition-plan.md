# 2026-05-24 — prior-art / sitemap 후속: 새 layer 추가 plan (v2)

상위 문서: [`docs/2026-05-24-tier1-tier2-followup-v2.md`](2026-05-24-tier1-tier2-followup-v2.md)
codex 리뷰: [`docs/2026-05-24-layer-addition-plan-codex-review.md`](2026-05-24-layer-addition-plan-codex-review.md)

본 v2 = v1 (8 후보 layer α~θ 평가) 의 codex 리뷰 반영 + ζ/γ/lastmod 실증 결과 반영.

## 핵심 정정 (v1 → v2)

v1 가정 "작은 port 비용 → 양의 EV" 가 잘못. codex 가 잡은 noise risk:

| 후보 | v1 평가 | v2 정정 |
|---|---|---|
| α MDR + probe 병합 | ★★★ multi-source recall ↑ | wrong block prompt 오염 risk. **prompt 통합 금지**. measurement-only 가능 |
| β MDR alignment | 1-2일 | 3-5일 (Cython + scipy clustering 우회 + equivalence test 누락) |
| γ /report autoscraper | ★★★ board-shape failed 회복 | register 회복 X 확인 (γ v2 = 0/4). registered config selector 수정 use case 만 |
| δ playwright+sitemap | ★★★ SPA 회복 | register timeout 침식 risk. offline prototype 만 |
| ε REPS port | ★★ signal 다양화 양의 EV | nav/menu noise 가능. bench-only, prompt 통합 금지 |
| ζ guard fix | ★★★ skku 회복 확정 | bench correction only. prod `_article_url_score` 는 이미 wide (`\d{3,}`) — prod 통합 불필요 |
| η sitemap auto-retry | ★★ 자동 회복 | 자동 retry 금지. *안내 message* 만 |
| θ adapter 분류기 | ★ | signal-only OK |

## ζ/γ/lastmod 실증 결과 (2026-05-24 본 turn)

| 항목 | 결과 | 액션 |
|---|---|---|
| ζ — mdr_guarded url-pattern regex `articleNo` 추가 | `skku_cse` R=0 → R=1.00. 다른 4 사이트 = 그대로 R=0 (다른 guard 정상) | bench correction 끝. prod 통합 X (`_article_url_score:502` 가 이미 충분) |
| γ v2 — triage_queue sitemap-있는 4 사이트 의 sitemap top URL 에 autoscraper triage | 0/4 recovered | sample 부적합 확인 (sitemap top = 개별 article / sitemap XML / SPA wrapper / 일반 페이지). γ 는 *register 회복* X. */report selector 수정* 만 가치 |
| lastmod observe sketch | 폴링 = `scripts/poll.py` cron 사이클당 모든 site fetch_list. site별 interval 없음. observe artifact = `output/sitemap_lastmod_log.jsonl` | sketch: [`experiments/sitemap-lastmod-bench/observe_only_sketch.md`](../experiments/sitemap-lastmod-bench/observe_only_sketch.md). A 묶음 구현 항목 #2 |

## A 묶음 — prod 통합 (이 turn 구현)

| # | 항목 | 위치 | LOC | risk |
|---|---|---|---|---|
| 2 | **lastmod observe-only** — `scripts/poll.py` 에 sitemap Range GET + log artifact. 실제 skip X | `scripts/poll.py` + `output/sitemap_lastmod_log.jsonl` | ~30 | 0 (observe-only) |
| 3 | **η reject message** — board_shape reject 시 sitemap top 후보 안내. 자동 retry X | `scripts/register.py` reject 분기 또는 `bot/worker.py` 사용자 응답 | ~20 | 작음 |
| 4 | **α digest field** — `engine/digest.py` 에 `mdr_candidates` 별 field 추가. prompt 영향 X (measurement only) | `engine/digest.py` + 새 helper | ~15 | 0 |
| 5 | **θ sitemap-only-fit signal** — canva/salesforce 처럼 *sitemap 만으로 polling 가능* signal 분류기 | `probe/discover.py` 새 signal | ~40 | 작음 (signal only) |

총 ~110 LOC. risk 다 작음. quality bar = "버그만 없음" (사용자 명시).

## B 묶음 — 별 작업 (이 turn 보류)

| # | 항목 | 위치 | LOC | 보류 이유 |
|---|---|---|---|---|
| 6 | γ /report autoscraper hook | `bot/` `/report` handler | ~80 | bs4 pin 회피 (stripped 차용 필요). 별 작업 단위 |
| 7 | ε REPS Py3 port + bench cell | `experiments/prior-art-bench/` | ~80 | bench 만, prod 통합 X. 후순위 |

## drop (v1 의 ★★★ 후보 중 net 음 EV)

| 후보 | drop 이유 |
|---|---|
| α prompt 통합 | wrong block (gamemeca 인기게임/arca pagination) prompt 오염. token cost ↑ |
| β MDR alignment | 비용 3-5일, benefit untested. 다른 우선순위 후 검토 |
| δ register-path playwright | timeout 침식, 기존 site attempt budget 잠식 |
| η sitemap auto-retry | sample 0. wrong URL 자동 등록 prod 오염 risk |
| ε prompt 통합 | bench 미실행 + noise 가능 |

## test / rollback (codex 지적 누락 보강)

A 묶음 각 항목 검증:

| 항목 | 검증 |
|---|---|
| 2 lastmod observe | `output/sitemap_lastmod_log.jsonl` 1 line 이상 append 확인. 기존 fetch_list 결과 변화 X (observe-only) |
| 3 η reject message | board_shape reject 발생 시 메시지에 sitemap 후보 URL 포함. 기존 reject 흐름 변경 X |
| 4 α digest field | digest JSON 에 `mdr_candidates` key 존재. 기존 key 변경 X. config_writer prompt 동작 X (key 안 읽음) |
| 5 θ signal | digest 또는 sitemap.json 에 `sitemap_only_fit` boolean 존재. 기존 signal 변경 X |

rollback: 각 항목 = 별 commit. 문제 발생 시 해당 commit revert.

## 본 plan 이 다루지 *않는* 것

| 범위 | 상태 |
|---|---|
| B 묶음 (6/7) 구현 | 별 작업 |
| α/β/δ/η/ε production prompt/path 통합 | drop 결정 |
| Firecrawl / rss-proxy / REPS prod | 보류 또는 drop (v2 §7 결정 유지) |
| A 묶음 외 새 후보 | 본 plan 범위 X |
