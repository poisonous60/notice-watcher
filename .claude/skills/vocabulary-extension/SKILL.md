---
name: vocabulary-extension
description: >-
  notice-watcher 의 closed vocab (engine strategy / source / transform) 확장 판단·디자인·박기 워크플로우.
  사용자가 "어휘 확장", "strategy 추가", "/vocabulary-extension" 라고 할 때.
  hand-config 가 출력한 임계 알림 보고 사용자가 손-호출. 자동 호출 X (ADR 0003).
  판단 rubric 형 — 절차 X, agent 가 후보 평가·design 자체 결정. 이 프로젝트 (`poisonous60/notice-watcher`) 전용.
---

engine 의 closed vocab 확장 = 매번 다른 design (절차형 X). SKILL 은 agent 가 *판단할 때 따르는 rubric* — step-by-step X. ADR `docs/adr/0003-vocabulary-extension-skill.md` 가 설계 결정 source of truth.

## 0. 진입 — 트리거

사용자 손-호출만:
- `/vocabulary-extension`
- "어휘 확장", "strategy 추가", "vocab-ext"
- hand-config 출력의 `[알림] vocab_candidates 임계 도달` 본 후 사용자 결정

자동 호출 X — hand-config 가 자체 판단으로 이 SKILL 호출 안 함 (ADR 0003 의 분리).

## 1. 후보 enumerate

```
python scripts/cases_index.py vocab-trigger --json
```

출력 = `triggered` (임계 도달) + `sub_threshold` (미달, 후보별 카운트) + `contradictions` (모순). 후보 0건 = backfill 권장.

`--no-write` 옵션 = alert history 적재 안 함 (검토만 할 때).

## 2. 후보 평가 rubric

각 임계 도달 후보별 4 차원 평가:

### 2a. 영향 사이트 수
- 현재 handwritten 중 이 후보 박으면 *config 자동* 으로 전환 가능한 사이트
- 미래 같은 패턴 사이트 추정 (선택)
- 영향 사이트 1 = ROI 낮음, ≥3 = ROI 높음

### 2b. engine 변경 범위
- strategy 코드 (`engine/strategies/<X>.py`) — 한 파일 / 여러 파일
- schema (`engine/config_schema.py`) — 새 키 / 기존 키 확장 / breaking
- prompt 어휘 (`prompts/config_writer.system.txt`) — 새 룰 추가 / 기존 수정
- fixture (`tests/probe_heuristics/`, `scripts/probe_smoke.py REPS`)

### 2c. 안전성
- **closed vocab 폭주** — 새 어휘 추가 시 LLM 어휘 학습 어려움 ↑. 자동률 ↓ 가능
- **backward compat** — 기존 14 config 깨짐? 새 키 = 선택 → 안전. 기존 키 의미 변경 → breaking
- **breaking 시 룰** (ADR 0003): 사용자 명시 confirm 강제 + migration script

### 2d. ROI 합산
- 영향 사이트 수 / 변경 비용 (시간) — 점수
- 모순 후보 (`contradictions` 목록) = 점수 ↓

### 2e. 결정
- 후보별 점수 → 최고 후보 1개 박기 또는 *지금은 다 보류*
- 보류 = case .md `vocab_candidates` 항목 유지 + commit msg 에 "보류 사유" 메모

## 3. 캐시 검증 (오염 방어)

선택 후보 박기 전 캐시 entry 검증:

### 3a. evidence path 재검증
각 case 의 `vocab_candidates.evidence` 의 path Read → 코드 실제 그 패턴인지 확인.
- evidence stale (코드 변경됐는데 reasoning 옛것) → 그 case 의 confidence 강등 또는 무시
- 정상 = 그대로 사용

### 3b. confidence labels
- `high` = baseline 채택. 단 evidence 1회 Read 필수.
- `med` = 간략 검토 (evidence Read + 1줄 sanity).
- `low` = **의무 재평가** — 단순 채택 X. 코드 직접 분석.

### 3c. failure feedback
case 에 `vocab_attempt_failed: true` 있나 확인 (이전 vocab-ext 시도 fail 기록).
- cases_index.py 가 자동 강등 1단계 (high→med, med→low) 반영.
- failed 후보 = 같은 design 으로 또 박지 X — 원인 (회귀 / 어휘 학습 영향) 분석.

### 3d. cross-evidence 모순
`contradictions` 목록 후보 = 진입 *알림 표시*. 자동 차단 X. agent 가 case 별 evidence 비교 후 판단:
- 한 case 는 어휘화 필요, 다른 case 는 closed vocab 으로 풀림 → 어휘 후보 *재정의* 가능.

## 4. design 단계 (agent 자체 결정)

선택 후보 → 구현 design. 절차 X — 후보마다 다른 작업.

체크리스트:
- 후보 → schema 형태 design (예: `list.pagination.kind: "click"` + 필드 enumerate)
- engine 코드 변경 위치 + 로직 design
- prompt 어휘 추가 — `prompts/config_writer.system.txt` 의 어느 섹션, 어떻게 표현
- fixture — `tests/probe_heuristics/`, `scripts/probe_smoke.py REPS`
- backward compat 확인 — 기존 14 config validate 통과?
- breaking change 시 — migration script (`scripts/migrate_<feature>.py --dry-run` / `--yes`) 박기

## 5. 박기 + 가드

ADR 0003 의 smoke scope 의무:

1. **probe_smoke** 그린 — `python scripts/probe_smoke.py`
2. **schema backward compat** — `python -c "import json; from engine.config_schema import validate_config; [validate_config(json.load(open(p, encoding='utf-8'))) for p in __import__('pathlib').Path('configs').glob('*.json')]"` (전체 14 통과)
3. **영향 사이트 회귀** — 이 어휘 후보 case .md 의 사이트 + 같은 strategy 사이트 — `python scripts/register.py --config configs/<slug>.json` 결과 baseline 과 동등/개선
4. **rollback 준비** — 영향 사이트 config 자동 `.bak` 백업 (vocab-ext 박기 직전)

### 5a. reviewer (commit 직전 — 필수)

hand-config-reviewer (codex 또는 claude agent) 호출. 위 §5 결과를 prompt 에 박음. reviewer rubric 의 추가 항목 (vocab-ext 진입 시 = `engine/strategies/` OR `transforms.py` OR `extract_helpers.py` OR `config_schema.py` 새 키 OR `prompts/config_writer.system.txt` 어휘 추가 *중 하나* 매칭):
- 9. 영향 사이트 회귀 결과 첨부
- 10. schema backward compat — 14 config validate 통과 (breaking change 시 migration script 강제)
- 11. prompt 어휘 변경 시 fail 케이스 재시도 결과 (해당 시)
- 12. prompt 어휘 ↔ schema/engine 일관성 — 새 어휘 토큰이 engine/ 실제 정의에 존재

FAIL → 사용자에게 보고. 자동 재호출 X.

## 6. 회수

박기 성공 시:

1. 영향 case .md 의 해당 `vocab_candidates` 항목에 `applied: <commit_sha>` flag 추가 (또는 deferred=false 로 변경)
2. `output/vocab_alerts.json` 정리 (선택 — history 보존도 가능)
3. commit msg:
   ```
   [vocab-ext] <candidate> 어휘 추가 — engine.strategies.<X> + schema + prompt
   - 영향 사이트: <slug1>, <slug2>, <slug3>
   - reviewer: PASS
   ```

박기 실패 (회귀 fail / reviewer FAIL):

1. 영향 case .md 의 해당 항목에 `vocab_attempt_failed: true` + `failed_at: <date>` + `failure_reason: <1줄>` 박음
2. 다음 vocab-ext = 그 case 의 confidence 자동 강등 (cases_index.py 가 처리)
3. `.bak` 으로 영향 config 복구
4. 사용자에게 보고

## 7. backfill 시 (별도 작업)

ADR 0003 의 backfill (과거 4 handwritten 어댑터) 작업 시:

각 handwritten case .md (ArcaLive / DaumCafe / NaverCafe / Reddit) 에 `vocab_candidates` frontmatter 박기:

```yaml
vocab_candidates:
  - candidate: <후보 이름>
    confidence: <high|med|low>
    evidence:
      - <adapters/<X>.py:line-range>
      - case_feedback: "<요약>"
    reasoning: "<1-3줄>"
    analysis_date: <YYYY-MM-DD>
    deferred: true
```

후보 분해 = 어댑터 코드 + 등록 시 fail feedback 보고 판단. ADR 0003 §Consequences 참조.

backfill = 권장 (선행조건 X). 미완료 = 신규 hand-config 시점부터 누적 시작.

## 관련

- `docs/adr/0003-vocabulary-extension-skill.md` — 설계 결정 source of truth (트리거 / 임계 / 캐시 / 오염 방어 / migration / backfill)
- `.claude/skills/hand-config/SKILL.md` — 사이트별 절차형, `vocab_candidates` append 만
- `scripts/cases_index.py vocab-trigger` — 임계 체크 + alert history
- `engine/config_schema.py` — 확장 대상 (새 strategy 박을 때)
- `prompts/config_writer.system.txt` — 어휘 학습 추가 자리
