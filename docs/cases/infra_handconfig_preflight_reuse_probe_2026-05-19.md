---
slug: infra_handconfig_preflight_reuse_probe_2026-05-19
url: (인프라 case — 특정 사이트 X. 트리거 = 사용자 메타 질문 — 다른 경로로 고친 사이트가 triage 큐에서 안 빠지는 경우 판단 절차)
status: 🏗 인프라 (hand-config SKILL.md §0b 추가 — preflight 이미 고쳐졌나 검사)
outcome: improved
date: 2026-05-19
fix_layer:
failure_keys: [skill_no_preflight_check, stale_queue_residue, sidewise_fix_not_recognized, batch_redundant_handconfig_work]
config_strategy:
adapters_changed:
engine_files_touched: [.claude/skills/hand-config/SKILL.md]
tags: [self-improvement, skill-infrastructure, preflight, queue-stale, sidewise-fix-recognition]
requested_by: 운영자 (dev box session — arxiv-2601-bench 7건 batch 진입 전 메타 질문)
---

## 트리거

운영자 질문: "지금 실패한 게 triage 큐에 쌓였거든. 방금 같은 방식으로 hand-config 스킬을 수행하는 게 아니라 *다른 경로로 사이트를 고쳤는데* triage 큐에서 안 빠진 경우는 어떻게 판단하지? hand-config 스킬 중에서 이미 고쳐졌는지 확인하는 절차가 있나?"

배경 = arxiv-2601-bench 7건 batch 시작 직전. 전 turn 의 Action C (`prompts/config_writer.system.txt` 4 룰 추가) 가 batch 의 4 사이트 (CNN/BBC/Vimeo/NatGeo) 회복 가능성 있음. SKILL.md 절차 따르면 §1 진단 → §2 분기 → §3 손-config 자동 진입 — *prompt 변경 효과 측정 없이* 손-config 작업 시작.

## 무엇이 일어났나

SKILL.md 의 자동 정리 메커니즘 검토:

1. **`register.py` 성공 시 `_save_state` 가 `.FAILED.json` + `triage_queue.jsonl` 자동 정리** (`scripts/triage.py:6`, SKILL.md §3 step 7)
2. **`triage.py pull --skip-later` 의 stale prune** — N100 에서 이미 REJECTED 마커 박힌 slug 의 옛 local FAILED.json 자동 삭제 (`scripts/triage.py:199-243`, sentinel `__OK__`/`__QOK__` 둘 다 출력 시 안전)

**둘 다 = 재시도 또는 N100 마커가 선행**. 사용자가 *제3 경로* (prompt / engine / probe / 인식기) 로 고치고 **재-등록 시도 안 하면 큐에 영원히 남음** — 다음 hand-config 작업이 *이미 자동 회복 가능한* 사이트에 손-config 박는 낭비 가능.

## 왜 문제인가

1. **직접 영향**: 본 batch 7건 중 CNN/BBC/Vimeo/NatGeo 4건 = 전 turn prompt 변경 영향 사이트. *§1 진단 진입* 하면 손-config 작업 시작 — 4건 중 0~4건이 prompt 변경 만으로 회복 가능한지 *측정 기회 상실*.
2. **재발 가능성**: 본 프로젝트 = 자가개선 인프라 (CLAUDE.md §6 + ADR 0003) 운영 — prompt / probe / engine 변경이 자주 일어남. 매 변경이 *기존 FAILED 큐* 에 영향 가능. SKILL.md 가 이걸 *인지하지 않으면* 매번 같은 낭비.
3. **자가개선 cycle 의 의도 위반**: 트랙 B (probe 일반화) 의 본질 = "같은 패턴 다시 안 들어오게". preflight 게이트 없으면 *과거 큐 처리* 가 트랙 B 의 효과 무시.

## 픽스 (fix_layer: A — SKILL.md 단일 파일)

### A-1. SKILL.md §0 와 §1 사이 새 §0b 박기

> **§0b. preflight — 이미 고쳐졌나 / 옆 작업이 큐를 stale 화했나**
>
> §1 진단 진입 *전*, 각 큐 slug 에 대해 두 검사:
>
> (a) **stale 큐 검사** — `configs/<slug>.json` 또는 같은 host 의 손-adapter 가 이미 존재하면 → `register.py --config configs/<slug>.json` (있으면) 또는 `register.py "<URL>"` (recognizer 매칭 시) 으로 재등록 시도. 성공 → 큐 자동 정리 → 본 slug 종료 (§1 진단 skip).
>
> (b) **옆 작업 회복 검사** — 큐 진입 *후* (FAILED.json 의 `failed_at` 이후) prompt/engine/probe/recognizer commit 있으면 → `register.py --reuse-probe "<URL>"` 1회 (기존 probe artifact 재사용, prompt+휴리스틱 만 바뀐 효과 측정). 성공 → 큐 정리 + §1 skip.
>
> (a)+(b) 둘 다 실패 시 → §1 정상 진입.
>
> 본 검사 결과 (a-hit / b-hit / both-miss) 는 §2 진입 전 강제 인용 6번 으로 인용 (skim 방지). 인용 형식 = `preflight: <a|b|miss> — <slug>`.

### A-2. SKILL.md §2 진입 전 강제 인용 항목 6 번 추가

기존 1~5 + 신규 6 = `preflight 결과` (a/b/miss). a 또는 b 면 §2 진입 자체 X (자동 회복) — 인용도 1줄로 끝.

## 영향

### 회귀 risk
- `register.py --reuse-probe` 는 기존 명령 — 사이드 이펙트 0 (probe artifact 재사용, 새 fetch X)
- (a) `register.py --config <existing>` 도 기존 — 성공 시 baseline 갱신, 실패 시 그대로
- SKILL.md 변경 = 문서만, 코드 변경 X. probe_smoke 영향 0

### 비용
- batch 처리 시 *추가 register.py 호출 N회* (큐 크기 만큼). 단 N 회 모두 reuse-probe → LLM 호출 1회 (≈ 5초). 큐 100건 = 500초 = 8분. acceptable.
- 회복 안 되는 케이스 (b-miss) 도 register.py 가 실패 응답 → §1 정상 진입. *추가 비용은 reuse-probe 의 5초만*.

### 영향 사이트 (즉시)
- 본 batch 7건 = preflight 적용
- 미래 모든 hand-config 진입 큐 = preflight 적용

## 검증

- SKILL.md 변경 = 텍스트만. `probe_smoke.py` 영향 X (코드 변경 0)
- 실증 검증 = 본 batch 7건 처리 결과 — 몇 건이 (a) 또는 (b) 로 회복하나, 손-config 작업 감소량 측정
- 회귀 검증 후속 = 다음 hand-config 진입 시 SKILL.md §0b 절차 수행 여부 (운영자 확인)

## 한계

- preflight 가 *register.py 비용* 회피 못 함 (reuse-probe 도 LLM 1회). 큐 매우 큰 경우 (100+ slug) batch 처리 시간 늘어남
- `failed_at` 이후 commit 자동 판정 = `git log --since=<failed_at> -- prompts/ engine/ probe/ engine/recognizers/` 같은 휴리스틱. 단 *prompt 변경이 정말 본 slug 에 영향* 인지는 LLM 시도 결과로만 확인 — preflight 는 *시도* 만 강제, *분석* 은 register.py 자체가
- (a) 의 `configs/<slug>.json` 존재 = 손-config 자체 stale 가능성 (사이트 layout 바뀜). reuse 가 실패하면 §1 진입 → 손-config 갱신. 본 case 의 *humblebundle* 가 그 예 — `configs/host_humblebundle-co_software_4589b229.json` 존재하나 큐에 다시 떴음

## 후속 작업

- 본 case commit 같은 PR 에 SKILL.md §0b 박음 + 본 batch 7건 처리 결과 적용
- 미래 후속: preflight 자동화 = `triage.py preflight` subcommand 신설 (`pull` 직후 옵션). 현재는 SKILL.md 절차 (사람이 명령 호출). 본 case scope 밖

## 자가 점검 (5-질문)

1. **어느 자리?** — fix_layer 없음 (SKILL.md = skill infrastructure layer, code 영향 0). reviewer rubric 의 A~F (E:schema / D:retry / C:probe / B:few-shot / A:prompt) 어느 쪽도 X — *meta-skill* 카테고리. prompt rot 영역도 X (`pipeline-rot-review`) — additive 인프라. 이전 SKILL 변경 인프라 case ([[infra_skill_cross_case_gate_2026-05-17]]) 도 fix_layer 비웠음.
2. **이전 케이스 있나?** — [[infra_skill_cross_case_gate_2026-05-17]] (skill cross-case lookup 강제 게이트) 와 *카테고리 같음* — SKILL.md 절차 보강. 다른 점 = cross-case 는 *진단 정합성*, preflight 는 *큐 stale 인지*.
3. **재발 방지?** — SKILL.md §0b 박힘 → 매 hand-config 진입 시 자동 적용. 별 자동화 (`triage.py preflight` subcommand) 는 후속.
4. **자가 의심?** — preflight 가 *false positive* (실제로 회복 안 되는 사이트를 회복으로 오인) 가능성? = X. register.py 의 검증 (post_id_unique 등) 이 다 통과해야 success — 회복 판정은 register.py 책임. preflight 는 *trigger 만*.
5. **회귀 검증?** — SKILL.md 텍스트 변경, 코드 변경 0. probe_smoke 영향 X. 실증 검증 = 본 batch 결과.
