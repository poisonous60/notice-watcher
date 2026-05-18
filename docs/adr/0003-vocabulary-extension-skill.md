# 0003 — vocabulary-extension SKILL: closed vocab 확장의 결정·실행 메커니즘

engine 의 closed vocab (4 strategy / 7 source / 19 transform) 확장 결정 = 매번 다른 design (절차형 X). 단 *판단 원칙*은 일관 필요 → 신규 SKILL `vocabulary-extension` (판단 rubric 형, 사용자 손-호출). hand-config 는 어휘 후보 append + 임계 알림만 — 자동 호출 X (매 진입 부담 + pipeline-rot-review 함정 회피).

## Context

closed vocab = bounded. 어휘 밖 사이트 = handwritten 폴백 (4/14 = 29%). 같은 어휘 후보 N건 누적 시 어휘 확장 ROI 발생. 단 현재 *결정·실행 메커니즘 X* (ad-hoc). hand-config 는 사이트별 절차형 — 매 진입마다 어휘 확장 평가는 스코프 과대.

pipeline-rot-review (curative 7 영역 검토) 가 작성 후 *실제 안 쓰임* — 트리거 vague (사용자 손-호출만, 까먹음). 같은 함정 회피 필요.

## Decision

### 분리 + 트리거
- **분리** — hand-config (사이트별 절차형) 는 case .md frontmatter `vocab_candidates` 에 후보 append 만. vocab-ext (어휘 확장 판단·박기) 는 별도 SKILL.
- **트리거** — vocab-ext = *사용자 손-호출만*. hand-config 자동 호출 X.

### 지속 알림 메커니즘 (차원 3)
한 줄 알림 = pipeline-rot-review 의 까먹음 실패와 충분히 다르지 X (codex 지적). **누적 alert history** 박음:
- `output/vocab_alerts.json` (gitignore, dev box) — 임계 도달 알림 누적 (timestamp / 후보 / 트리거 카운트)
- `cases_index.py --check-vocab-trigger` 가 매 호출 시 history 적재 + 누적 카운트 출력
- hand-config 출력 끝에: `[알림] vocab_candidates 임계 도달: click_pagination = 3건 / 알림 누적 12회 — /vocabulary-extension 호출 권장`
- 누적 카운트 ↑ = noise pressure ↑ = 사용자 무시하기 어려움
- (follow-up) dashboard `/vocab-deferred` 페이지 별도 작업 — *현재 ADR 범위 외*

### 캐시 + 카운트
- **캐시 위치** — case .md frontmatter `vocab_candidates: [{candidate, confidence, evidence, reasoning, analysis_date}]`. 사이트별 자연 묶임.
- **카운트** — cases_index.py 가 case .md frontmatter scan → 후보별 누적 + confidence 분포.

### 임계 + confidence 룰 (차원 6)
- **임계 N = 3건** (deferred_heuristics 와 동일).
- **confidence 조합**:
  - `high ≥1 + 같은 후보 ≥3건` = 즉시 진입 권장
  - `med ≥3건` = 진입 권장
  - `low only` = 보류 (의무 재평가 강제)
- **모순 시** — 같은 candidate 의 case 들이 모순 evidence (예: 한 case 는 어휘화 필요, 다른 case 는 closed vocab 으로 풀림) → vocab-ext 진입 시 *알림 표시*, 자동 차단 X (agent 판단).

### 오염 방어 4중 (차원 2 = codex PASS)
- (a) evidence path 재검증 — 코드 grep
- (b) confidence labels — low = 의무 재평가
- (c) failure feedback — vocab-ext 박은 후 fail = case .md 에 `vocab_attempt_failed` flag, 다음 agent 자동 강등
- (d) cross-evidence 모순 검출 — cases_index 출력에 모순 후보 표시

### agent 분리
- cases_index = 카운트 (기계, 판단 X)
- hand-config agent = 후보 append + 진입 결정 (사이트 처리 맥락)
- vocab-ext agent = 박기/보류 판단 (rubric)

### Schema breaking change + migration (차원 4)
vocab-ext 가 박은 어휘 = 모든 사이트 영향. 룰:
- **backward compat 우선** — 새 키 = 선택 (기존 config 깨짐 X)
- **breaking change** (기존 config 무효화) = 사용자 명시 confirm 강제 + migration script 박기 (`scripts/migrate_<feature>.py --dry-run` / `--yes` 패턴)
- **smoke scope** — vocab-ext 박은 후 의무 검증:
  - `python scripts/probe_smoke.py` 그린
  - 14 사이트 register --config 통과 (schema validate + fetch_list 1건)
  - 영향 사이트 (이 어휘 후보 박힌 case .md 의 사이트) 회귀 — register --config 결과 baseline 과 동등 또는 개선
- **rollback** — vocab-ext 박기 전 영향 사이트 config 자동 `.bak` 백업. fail 시 `.bak` 복구.

### Backfill (차원 5)
- backfill = ADR 적용 *직후 권장 작업*, **선행조건 X**.
- 미완료 = 신규 hand-config 시점부터 누적 시작 = 첫 임계 도달이 늦어질 뿐.
- 별도 1회 작업 — 과거 4 handwritten 어댑터 (ArcaLive / DaumCafe / NaverCafe / Reddit) case .md 에 `vocab_candidates` 박기.

## Considered Options

- **hand-config §2.2f 분기 추가** — 사이트별 스코프 깨짐 + 매 진입 부담. 기각.
- **신규 SKILL + hand-config 자동 호출** — 매 진입마다 vocab-ext 호출 평가 부담. 기각.
- **신규 SKILL X, docs/ 절차만** — 자동 트리거 X = 까먹기. pipeline-rot-review 가 검증한 실패 패턴. 기각.
- **별도 `_deferred_strategies.md` 파일** — case .md 와 동기 부담. case .md frontmatter 가 단일 진실원. 기각.
- **한 줄 알림만 (지속 X)** — pipeline-rot-review 함정. 기각 (codex 지적).

## Consequences

- **trigger 자동화 = X** (Q1 의 비용/정책/호스트 제약과 동일). 사용자 손-호출 + 누적 alert history 로 보완.
- **vocab-ext 박은 어휘 = 모든 사이트 영향** — reviewer subagent rubric 확장 + 14 사이트 회귀 + .bak rollback 으로 가드.
- **캐시 오염 가능** — 4중 방어로 줄임. *근본 진실 = case .md + 코드*, 캐시 = 지름길.
- **dashboard 페이지 = follow-up** — vocab-ext 첫 운영 후 빈도 보고 결정.

## Implementation outline

1. `.claude/skills/vocabulary-extension/SKILL.md` 신규 — 트리거 / 후보 평가 rubric / design / 박기 / 회수 / 가드 (위 룰).
2. case .md frontmatter 스키마 확장 — `vocab_candidates: [...]` (선택 키).
3. `scripts/cases_index.py query --vocab-candidate <name>` + `scripts/cases_index.py vocab-trigger [--silent-if-empty] [--json]` 명령 신규.
4. `output/vocab_alerts.json` history 적재 (gitignore) — **후보별 keyed** (candidate → first_seen_at / last_seen_at / alert_count / last_trigger_count).
5. hand-config SKILL.md §6.7 한 줄 추가 — 어휘 후보 떠올랐으면 case .md `vocab_candidates` append.
6. hand-config SKILL.md §5 commit 후 `vocab-trigger --silent-if-empty` 호출 — 임계 도달 또는 모순 시만 출력.
7. reviewer subagent rubric 확장 — vocab-ext 진입 시 추가 검증 **4항목** (9. 영향 사이트 회귀 / 10. schema backward compat / 11. prompt 어휘 변경 시 fail 케이스 재시도 / 12. prompt 어휘 ↔ schema/engine 일관성). 진입 휴리스틱 = `engine/strategies/` OR `engine/transforms.py` OR `engine/extract_helpers.py` OR `engine/config_schema.py` 새 키 OR `prompts/config_writer.system.txt` 어휘 토큰 추가 *중 하나* 매칭.
8. (권장) backfill — 과거 4 handwritten case .md 에 `vocab_candidates` 박기 (별도 작업).
9. (follow-up) dashboard `/vocab-deferred` 페이지 — 별도 작업.
