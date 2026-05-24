# prior-art / 알고리즘 차용 layer = measurement-only 로 먼저 도입, evidence 후 prompt/gate 통합 결정

## Context

2026-05-24 prior-art follow-up (`docs/2026-05-24-tier1-tier2-followup-v2.md`) 에서 외부 알고리즘 / 신호 layer 8개 후보 평가 (MDR `list_candidates`, MDR alignment, autoscraper seed-based, playwright+sitemap chain, REPS, mdr_guarded, sitemap auto-retry, sitemap-only adapter 분류기). 도입 비용은 대부분 작음 (port LOC ~50-200, runtime API 없음, key 없음). 직관 = "port 비용 작음 → 양의 EV → 다 박자".

Codex 리뷰 (`docs/2026-05-24-layer-addition-plan-codex-review.md`) 가 정정: **net 음의 EV 시나리오 다수**:

| 후보 | 음의 EV 시나리오 |
|---|---|
| α MDR + probe 병합 (prompt) | wrong block (gamemeca 인기게임 / arca pagination) prompt 오염 + token cost ↑ |
| ε REPS prompt 통합 | nav/menu 반복 후보 noise + token cost ↑ |
| δ playwright + sitemap register-path | register timeout 침식, 기존 site attempt budget 잠식 |
| η sitemap auto-retry | sample 0, wrong URL 자동 등록 → prod 오염 |
| β MDR alignment field map | wrong block alignment 가 그럴듯한 field selector 만들어 오염 |

5 codex 실험 (gate signal A, lastmod D, MDR vs probe #1, mdr_guarded #2, autoscraper triage #3) 의 결과도 "prompt/gate 직접 통합" 은 정당화 안 됨:
- A: 8 in-scope entry 모두 drop 카테고리 → 측정 불가
- D: 33% coverage, mean savings 1423x (outlier 영향)
- #1: MDR = probe = skku 1/5 win, 4/5 동등 실패
- #2: guards 과탐 R=0 → guard 약화 후 skku 회복 (bench correction)
- #3: 0/8 (sample 부적합 — board-shape 아님)

근본 패턴: **"signal 다양화는 양의 EV" 라는 추측이 wrong-block 분류 능력 없는 신호에는 부정확**. 단 *side-bench only* 도 답 X — prod 실 데이터 distribution 못 봄 (synthesizer 5 site 외 일반화 신호 없음).

## Decision

새 prior-art / 알고리즘 차용 layer 는 **measurement-only / observe-only / message-only** 로 먼저 prod 도입. evidence 축적 후 prompt/gate 통합 여부 결정.

3 형태:

| 형태 | 의미 | 예 |
|---|---|---|
| **measurement-only** | digest dict 에 새 key 추가, prompt/gate 가 *읽지 않음*. evidence artifact | `mdr_candidates` (α), `sitemap_only_fit_signal` (θ) |
| **observe-only** | 새 action (e.g. sitemap HEAD) 수행, 결과 log 만, 기존 흐름 영향 X | lastmod log (poll cycle 당 1 줄, fetch_list skip 결정 안 함) |
| **message-only** | 사용자 향 메시지에 hint 추가, 자동 retry/등록 안 함 | board_shape reject 메시지에 sitemap top 후보 안내 (η) |

**금지** (이번 ADR 의 hard rule):

- 새 알고리즘 신호를 *직접 prompt 에 통합* 하기 — wrong-block 가능성 측정 전
- 새 신호로 *자동 retry / 자동 등록* 하기 — sample 0 일 때 prod 오염
- 새 신호로 *gate 통과 / 거부 결정 변경* — 1주~N주 evidence 없이

**평가 기준 (활성화 trigger)** = layer 별 별도 정의. 예 (lastmod observe):
- `false_skip_pct < 1%` (would_skip=true 면서 new_count>0 비율)
- `wasted_fetch_pct > 30%` (would_skip=false 면서 new_count=0 비율)
- coverage ≥ 30%
- 셋 다 만족 시 활성화 검토

evaluation script 는 ADR 의 *별 트랙* — 본 ADR 은 *형태/금지 룰* 만 결정.

## Considered alternatives

- **측정 없이 바로 prompt/gate 통합** — 기각. wrong-block 후보가 LLM selector 선택 오염 + token cost ↑ + 기존 회복률 regression 가능. codex 가 net 음의 EV 시나리오 5건 잡음
- **전혀 도입 안 함 (다 drop)** — 기각. prod 실 데이터 distribution 못 봄. 1주 후 "도입했어야 했나" 후회 가능. side-bench 5 site = 일반화 신호 부족
- **side-bench (`experiments/`) 만, prod code 손 안 댐** — 기각. 실 사이트 100+ 의 distribution 못 봄. side-bench fixture 가 represent 안 함
- **A/B (50% 사이트 신호 추가, 50% control)** — 기각. 이번 단계엔 over-engineering. 1차 measurement-only 결과 보고 A/B 필요 시 그때

## Consequences

**득**:
- noise risk 회피 — wrong-block 신호가 prompt 오염하기 *전에* 측정으로 잡음
- evidence-기반 결정 — 1주~N주 후 distribution 보고 활성화 trigger 만족 여부로 결정
- rollback 쉬움 — measurement-only 항목은 별 key/log 삭제만으로 revert (기존 흐름 변경 0)
- 후보 layer 가 dead code 인지 *실증* — 1주 후 mdr_candidates 가 0 의미 있는 cand / sitemap_only_fit_signal 가 거의 false 면 drop 판단 근거

**실**:
- dead code 될 위험 (1주 후 거의 0 hit / 도움 안 됨 → 제거 별 commit)
- log artifact 누적 — unbounded append (rotation 별 작업 필요, 본 ADR 범위 X)
- digest size 증가 — measurement key 추가로 digest JSON 약간 커짐 (현재는 무시 가능, 신호 다수 추가 시 cap 필요)
- evaluation script 미작성 — 1주 후 손-evaluation 필요 (별 작업)

**미해결 (별 트랙)**:
1. **evaluation script** — `output/sitemap_lastmod_log.jsonl` 분석 + `output/probe/*/digest.json` 의 `mdr_candidates` / `sitemap_only_fit_signal` 통계. 본 ADR 은 trigger 룰만 정의, 코드 X
2. **threshold 정의** — 각 layer 별 활성화 trigger (false_skip_pct 등) 의 *숫자* 는 evidence 본 후 조정 가능
3. **prompt 통합 시 선언적 룰** — measurement-only → prompt 활성화 시점에 *어떻게* prompt 에 박을지 (별 hint 라벨 / source 표시 / 우선순위 지시) 는 그때 별 ADR 또는 plan
4. **log rotation** — `output/sitemap_lastmod_log.jsonl` 가 unbounded. 1년 ~ 350-900 MB 추정. rotation 정책 별 commit
5. **drop trigger** — 1주 후 distribution 본 후 dead code 판단 시 *어느 commit 으로* 제거하는지 (별 ADR 또는 trivial commit)

## 적용 사례 (2026-05-24 A 묶음)

이 ADR 의 첫 dogfood:

| 항목 | 형태 | 위치 |
|---|---|---|
| α `mdr_candidates` | measurement-only | `engine/_mdr_candidates.py` + `engine/digest.py` |
| θ `sitemap_only_fit_signal` | measurement-only | `engine/digest.py` |
| lastmod observe | observe-only | `scripts/poll.py` + `output/sitemap_lastmod_log.jsonl` |
| η reject hint | message-only | `scripts/register.py:621` board_shape reject 분기 |

commit: `d90b256` (2026-05-24). 모두 codex bug review 통과 (`docs/2026-05-24-layer-addition-codex-bug-review.md`).

## cross-ref

- ADR 0003 (vocabulary-extension-skill) — 어휘 확장도 *evidence 축적 후 박기* 같은 패턴. 본 ADR 은 그 일반화
- ADR 0007 (LLM veto over reject gates) — gate 결정에 LLM 추가했던 패턴. 본 ADR 은 *gate 변경 전 measurement* 강제
- ADR 0011 (auto target = 새 글 올라오는 곳) — register 대상 정의. 본 ADR 의 measurement layer 가 이 정의 유효성 검증에 활용 가능
- `docs/2026-05-24-tier1-tier2-followup-v2.md` — bench 종합
- `docs/2026-05-24-layer-addition-plan.md` — A 묶음 plan + drop 항목
- `docs/2026-05-24-layer-addition-codex-bug-review.md` — codex bug review (MED+LOW fix 박은 commit 의 근거)
