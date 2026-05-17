---
slug: infra_skill_cross_case_gate_2026-05-17
url: (인프라 case — 특정 사이트 X. 트리거 = 사용자 비판 "5건째도 보류 6건째도 보류" 의 메타 원인)
status: 🏗 skill-infrastructure (cross-case lookup 강제 게이트 — cases_index.py query + SKILL.md §2 진입 전 5번)
outcome: improved
date: 2026-05-17
fix_layer:
failure_keys: [skill_cross_case_lookup_missing, deferred_heuristic_moving_target, cases_index_query_command_missing]
config_strategy:
adapters_changed:
engine_files_touched: [scripts/cases_index.py, .claude/skills/hand-config/SKILL.md, docs/cases/_deferred_heuristics.md]
tags: [self-improvement, skill-infrastructure, cross-case-gate, cases-index-query, deferred-tracking]
requested_by: 운영자 (dev box session)
---

## 트리거

사용자 비판: **"지난번 사이트 5개 줘서 보류였는데 6개일 때도 보류야. 대체 얼마나 더 해야 probe 개선하는건데"**.

근본 원인 = SKILL §6.2 "이전 케이스 있나?" 가 *가이드라인 권고* 라 매번 잊힘. cross-case 검색 도구도 없어서 매번 grep 으로 ad-hoc 검색 → 휴리스틱 박을 임계 (`N건째`) 가 moving target. `_deferred_heuristics.md` 의 후보 4건 중 2건 이미 N≥3 누적인데 안 박힘:
- `_external_only_check` — 4건 누적 (mdn/wiki/encyclopedia/poly-pizza)
- `_multi_host_hub_check` — 3건 누적 (tistory/wiki-mirror/reject)

> `fix_layer` frontmatter 는 비워둠 — 6 layer (E/D/C/B/A/F) 가 `scripts/cases_index.py` (script 헬퍼) 와 `.claude/skills/hand-config/SKILL.md` (skill 룰) 같은 *skill-infrastructure* 변경을 정의 안 함. F = engine/strategies/adapters/recognizers/register.py 플로우 한정. 향후 layer 분류 확장 필요 시 별 case.

## 픽스 (skill-infrastructure — 3 파일)

### 1. `scripts/cases_index.py` — `query` sub-command 추가

```
python scripts/cases_index.py query --failure-key <key>     # frontmatter failure_keys 직접 인덱싱
python scripts/cases_index.py query --signal "<regex>"      # case .md 본문 grep (multi-line, case-insensitive)
python scripts/cases_index.py query --fix-layer <L>         # 같은 fix_layer 만
python scripts/cases_index.py query --status-emoji <emoji>  # 상태 이모지로 필터
python scripts/cases_index.py query --deferred              # _deferred_heuristics.md 의 트리거 줄과 case 매칭
python scripts/cases_index.py query --json                  # 기계 가독 (skill 자동 게이트용)
```

각 label 마다 누적 N건 + `track_b_trigger: N≥3` flag. 손작업 grep 시간 0 → 1초.

기존 `cases_index.py` (frontmatter → INDEX.md / DB backfill) 와 backwards-compat — `sys.argv[1]=='query'` 분기로만 sub-command 라우팅 (argparse subparser 안 흔듦).

### 2. `.claude/skills/hand-config/SKILL.md` — §2 진입 전 강제 인용 5번 추가 + §6.2 강화

기존 4번 (last_feedback / verdict / 매칭 §번호 / 분기 후보) + 새 5번 (**누적 cross-check**):
- 진단한 failure_keys 마다 `cases_index.py query --failure-key <key> --json` 호출 + JSON 인용
- root-cause 신호 (static_vs_headless 등) 있으면 `--signal "<regex>"` 동시
- `--deferred --json` 으로 deferred 트리거 상태 확인
- **한 label `track_b_trigger=true` → 트랙 B 진입 강제, deferred 보류 불가** (사용자 비판의 직접 해결 — N+1 fallacy 차단)

§6.2 가이드라인은 `cases_index.py query` 명령 명시 + 강제 게이트는 §2 진입 전이라 표시.

### 3. `docs/cases/_deferred_heuristics.md` — [lifted] 표시

별 case `infra_probe_static_drift_url_penalty_2026-05-17.md` 가 박은 2개 후보 (`cross_parent_aggregate_tile_pattern` / `first_article_url_query_heavy_penalty`) 를 [lifted] 표시.

## 자가 점검 (§6 — 변형: skill-infra 라 표준 layer 분류 밖)

1. **자리**: skill-infrastructure (6 layer 밖). frontmatter `fix_layer` 빈 칸.
2. **이전 케이스**: 없음 — *cross-case lookup 도구 자체* 가 처음. 이 도구 만들기 전엔 grep 으로만 가능.
3. **누구 깰까**: 0 — 기존 명령 형식 보존. 새 sub-command 만 추가.
4. **검증**:
   - `cases_index.py query --failure-key posts_nonempty_0` → 3건 누적, track_b_trigger=true ✓
   - `cases_index.py query --signal "static.{0,5}headless|JSON.island"` → 4건 ✓
   - `cases_index.py query --signal "diverging_first_article"` → 5건 ✓
   - `cases_index.py query --deferred --json` → 4 후보 중 2 후보 `track_b_trigger=true` 검출 ✓
   - probe_smoke PASS (cases_index 추가만, probe heuristic 변경 X)
5. **outcome=improved, fix_layer=(빈 칸 — skill-infra), commit prefix `[skill-infra]`**.
6. **fixture**: 신규 fixture X (cases_index 는 script 헬퍼라 unit test 폴더 밖 — probe_heuristics 범위 아님).
7. **트랙 B 0건 사유**: 본 case 가 *cross-case 게이트 인프라 자체*. 추가 일반화 후보는 본 게이트 작동 후 다음 case 처리 때 자동 검출됨.
