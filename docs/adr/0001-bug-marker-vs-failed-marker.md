# 코드 버그 카테고리 (`.BUG.json`) 신설 + bug-fix workflow 분리

## Context

지금까지 `/watch`·`/preview` 등록 처리 실패는 두 카테고리 만 있었음:
- `.REJECTED.json` — board_shape rc=3 / policy rc=2 / admin reject (영구 거부)
- `.FAILED.json` — LLM gen 실패 / preflight 실패 등 (hand-config pipeline 대상)

`is_rejected(slug)` 가 둘 다 잡아 같은 slug 후속 잡의 subprocess 재시도 차단.

문제: chromium_lock timeout (rc=-1), subprocess timeout (rc=-2), 봇 반복 죽음 (attempts 초과), worker 예외 (rc=-99) 같은 **시스템 측 결함** 은 위 두 카테고리 어디에도 안 들어감. 현재 코드 = 마커 안 박고 사용자 ack 만 띄움 → 같은 URL 후속 잡은 fresh subprocess 재시도 → 같은 결함 재현 → 같은 사용자가 N번 같은 응답 받음, operator 가 인지하기 어려움.

## Decision

세 번째 카테고리 `.BUG.json` 신설. 의미 = "처리 중 멈춤" (코드 버그 / 외부 라이브러리 / 시스템 jam). hand-config pipeline (사이트 구조 인식 실패) 와 별도 카테고리 — **bug-fix workflow** (코드 자체 수정).

- rc 매핑: rc=-1/-2/-3/-5/-99 → `.BUG.json`. rc=1 → `.FAILED.json` 유지. rc=2/3 → `.REJECTED.json` 유지.
- 헬퍼: `is_blocked(slug)` = REJECTED+FAILED+BUG 합집합 + `marker_kind(slug)` 종류 구분.
- 사용자 ack: BUG 시 "처리 중 문제 — 운영자 점검 중. 점검 끝날 때까지 같은 응답이 와요." OWNER DM X. 자동 재시도 X.
- attempts 임계 = 5 → 2 (한 번 봐주고 두 번째 죽음에 BUG 박음).
- clear 경로: (1) bug-fix workflow 마지막 step (2) dashboard `/bugs` Clear (3) `/admin clear-bug <slug>`.
- 새 admin 명령: `/admin bugs` (목록), `/admin clear-bug <slug>` (제거).
- 새 dashboard 페이지 `/bugs` — slug/url/시각/rc/횟수/tail/Clear.

## Why

"멈추는 = 무조건 버그" — 시스템 측 결함은 사용자 책임 아님, operator 가 root cause 풀어야 함. hand-config pipeline 과 의미·해결 절차 다름 (사이트 인식 vs 코드 수정) → 같은 마커·같은 워크플로 로 묶으면 운영 혼란.

## Considered Options

- **Transient retry** (rc=-1/-2/-99 마커 안 박고 fresh retry) — 같은 결함 재현 시 사용자가 N번 같은 응답, operator 인지 어려움. 기각.
- **hand-config pipeline 통합** (`.FAILED.json` 에 합침) — 카테고리 의미 혼탁. hand-config = 사이트 구조 진단, bug = 코드 디버깅. 절차·도구 다름. 기각.
- **attempts 만 사용** (마커 X, 카운터 만) — 진입 시점 사용자 향 차단 신호 없음. 같은 slug 새 잡 매번 fresh subprocess. 기각.
