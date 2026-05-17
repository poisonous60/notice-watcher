---
slug: infra_retry_feedback_enrich_2026-05-17
url: (인프라 case — 특정 사이트 X. 트리거 = retry 메커니즘 개선 Phase 3)
status: 🏗 인프라 (retry feedback 풍부화 — prev cfg selector echo + probe top patterns 재표시 + attempt history)
outcome: improved
date: 2026-05-17
fix_layer: F
failure_keys: [retry_same_selector_repeat, llm_forgets_prev_cfg, probe_patterns_buried, no_attempt_history]
config_strategy:
adapters_changed:
engine_files_touched: [generate/generator.py]
tags: [self-improvement, retry-feedback, prev-cfg-echo, probe-patterns-echo, attempt-history, same-fail-detection]
requested_by: 운영자 (dev box session, retry 메커니즘 개선 후속)
---

## 트리거

Phase 2 (`infra_extra_signal_hints_2026-05-17`) 완료 후 Phase 3 (Codex 우선순위 2 — feedback trace 풍부화) 진행.

진단:
- `generate/generator.py:164` 에서 `prev_feedback = rep.feedback_text()` — 검증 보고 텍스트만 retry prompt 에 들어감
- LLM 이 자기 직전 시도의 strategy/selector 가 *뭐였는지* 잊음 (prompt 안에 prev_config JSON 박혀 있지만 125k 컨텍스트 안에 묻혀 무시)
- probe 가 본 top repeating patterns 도 digest meta JSON 안에 묻혀 LLM 이 selector 후보 다시 못 찾음
- attempt 누적 history 가 prev_feedback 에 없음 — 같은 방향 반복 감지 X

## 픽스 (fix_layer: F — 1 파일)

### F-1. `generate/generator.py` — `_enrich_retry_feedback(rep, prev_cfg, digest, attempt_history)` 신규

`rep.feedback_text()` 베이스 + 세 가지 보강:

**(1) 직전 시도 cfg 핵심 필드 echo**
- `strategy`, `list.row_selector` / `list_path`, `list.url_template`, `article.fetch_kind`,
  `article.content` selector, `article.url_template`
- "같은 selector 살짝 변형은 똑같이 실패한다 — 방향 자체를 바꿔라"

**(2) probe 정적 HTML 의 top 3 repeating patterns 재표시**
- `digest.list_candidates.html_repeating_patterns` 를 `child_count` 내림차순 정렬해 top 3
- 각 entry 의 selector / child_count / href_pattern_guess / sample_url 박음
- "같은 호스트 글 링크 가진 게 진짜 보드 후보. nav/footer 는 건너뛰어라"

**(3) attempt history 누적**
- retry loop 가 `attempt_history: list[dict]` 누적 — 각 attempt 의 strategy / row_selector / fail check 이름들
- 같은 hard fail 2회 이상 반복 시 "같은 방향으론 절대 안 풀린다. strategy 자체 또는 selector root 바꿔라.
  본문 fail 반복이면 body_empty_acceptable 검토" 경고 강조

### F-2. `generate_config_validated` 의 retry loop 보강
- `attempt_history: list[dict] = []` 추가
- 하드 실패 시 `attempt_history.append({n, strategy, rows, fails})` + `_enrich_retry_feedback` 호출 결과를 `prev_feedback` 에

## 효과 (예상)

- LLM 이 직전 시도 selector 를 *명시 텍스트* 로 다시 봄 → 단순 변형 반복 가능성 ↓
- probe top 3 patterns 가 retry prompt 앞쪽에 명시 → LLM 이 selector 후보 재선택 가능
- 같은 hard fail 2회 반복 시 명시 경고 → ncs-go-kr 류 (검증 종류 매 attempt 다른 케이스) 처럼 다양한 방향 시도 유도

## 검증

- `python scripts/probe_smoke.py --stage 3 --stage 5`: 312 PASS 0 FAIL
- `_enrich_retry_feedback` 직접 호출 시뮬레이션 (piku 가짜 cfg + 3 attempt history):
  - attempt 1 fail → prev cfg echo + probe top 3 patterns 박힘
  - attempt 2 fail (history 1건) → history 누적 표시
  - attempt 3 fail (history 2건, 같은 fail 반복) → ⚠ 경고 박힘

## 한계

- `generate.validate.feedback_text()` 자체는 미변경 — caller 가 별도 보강. 다른 호출자(없음) 영향 X
- attempt history 의 "같은 fail" 감지는 fail check 이름 set 비교 — detail 미세 차이는 못 봄
- selector 매치 횟수 trace (정적 HTML 안에 selector 매치 0건 명시) 는 Phase 4 영역 — adapter 가 trace 남기게 해야 가능. 큰 작업이라 보류

## 후속 작업

- Phase 4 (옵션): adapter 가 selector 매치 횟수 trace 남기게 → feedback 에 "row_selector 정적 HTML 매치 N건" 명시
- max_attempts 4→3 + early stop (Codex 우선순위 5) — 같은 fail 2회 반복 시 attempt 3 생략
