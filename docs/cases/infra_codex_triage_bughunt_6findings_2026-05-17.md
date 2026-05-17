---
slug: infra_codex_triage_bughunt_6findings_2026-05-17
url: (인프라 case — codex bughunt 후 6 findings 일괄 fix)
status: 🏗 인프라 (state machine 일관성 6 finding 일괄 fix + 회귀 테스트)
outcome: improved
date: 2026-05-17
fix_layer: F
failure_keys: [marker_lifecycle_inconsistency, migrate_marker_corruption, ssh_failure_silent_prune, save_rejected_sibling_leak, save_bug_no_cleanup, rc3_manual_orphan]
config_strategy:
adapters_changed:
engine_files_touched: [scripts/migrate_slug_schema.py, scripts/triage.py, scripts/register.py, scripts/probe_smoke.py, bot/worker.py, tests/state_lifecycle/test_marker_lifecycle.py, tests/state_lifecycle/__init__.py]
tags: [self-improvement, codex-review, state-machine, marker-lifecycle, defensive-sync]
requested_by: 운영자 ("triage 큐 관련해서 codex 가 버그 찾아봐")
---

## 트리거

운영자가 직전 fix (worker rc=2 double-record + triage.py pull reverse-delete) 후 codex 에 triage 큐 서브시스템 광범위 버그 헌트 의뢰. read-only sandbox + 명확한 6 카테고리 (상태 전이 / race / silent failure / stale drift / rc 일관성 / slug migrate) 로 prompt 작성. codex 가 6 findings 보고.

## 발견 (codex bughunt 결과)

| # | severity | 위치 | 요약 |
|---|---|---|---|
| 1 | **critical** | `migrate_slug_schema.py:72-83, 187-194` | `.REJECTED.json` / `.BUG.json` 이 normal state file 로 변환 — marker 손실 + 위장 등록 (data corruption) |
| 2 | major | `triage.py:cmd_pull` (방금 추가한 reverse-delete) | ssh ls 실패 시 `remote_failed=set()` → 모든 local FAILED stale 판정 → 일괄 삭제 |
| 3 | major | `triage.py:cmd_pull` + `register.py:_prune_triage_queue` | N100 의 `triage_queue.jsonl` 사라져도 local 영구 stale |
| 4 | major | `register.py:_save_rejected` | `.FAILED.json` 만 지움. `.BUG.json` / `<slug>.json` (normal state) 잔존 → race 시 중복 marker + `_load_states` (poll.py:204) 가 marker 형제 검사 안 해 stale 폴링 위험 |
| 5 | major | `register.py:_save_bug` + `worker.py:320` | BUG 마커 박을 때 `.FAILED.json` 안 지우고 `_prune_triage_queue` 도 안 부름 → dashboard `/triage/failed` 에 stale 표시 |
| 6 | major | `register.py:1289, 1332` | manual `register.py` 직호출 rc=3 경로 (nav_only / board_shape) 가 `_learn_pattern` 만 호출. `.REJECTED.json` 안 박음 → learned 됐는데 marker 없는 orphan |

## 픽스 (fix_layer: F — 6 파일 변경)

### F-1. `scripts/migrate_slug_schema.py` (#1 critical)

`_MARKER_SUFFIXES = (".FAILED", ".REJECTED", ".BUG")` + `_STATE_FILE_SUFFIXES = (".json", ".FAILED.json", ".REJECTED.json", ".BUG.json")` 상수 export.

- `build_mapping` L72-86: stem 추출 시 3 marker suffix 모두 strip — mapping key 가 *순수 slug*. 옛 코드는 `.FAILED` 만 strip → `.REJECTED.json` 의 stem 이 `<slug>.REJECTED` → rename 시 marker 손실.
- `rename_state` L187-194: 4 suffix 모두 iterate → marker suffix 보존.

### F-2. `scripts/triage.py:cmd_pull` (#2 + #3)

ssh ls 응답 신뢰성 sentinel 추가:
- `__TRIAGE_PULL_OK__` (FAILED.json 목록 끝) + `__TRIAGE_QUEUE_OK__` / `__TRIAGE_QUEUE_MISSING__` (queue 존재 여부) 두 sentinel 모두 출력에 있을 때만 `remote_response_trusted=True` → reverse-delete 진행.
- ssh 실패/timeout → sentinel 없음 → sync delete *전부 skip* (local 보존 default-safe). stderr 에 경고.
- queue reverse-delete: N100 에 `triage_queue.jsonl` 자체가 없으면 local 도 unlink (N100 `_prune_triage_queue` 가 last entry 삭제 시 파일 unlink — local 만 잔재 시 영구 stale).

### F-3. `scripts/register.py:_save_rejected` (#4)

`.FAILED.json` 만 지우던 옛 코드 → `.FAILED.json` + `.BUG.json` + `<slug>.json` 모두 삭제. 이유:
- REJECTED 는 marker_kind 우선순위 최고 (rejected > bug > failed) — 다른 marker 잔재 무의미
- `<slug>.json` (정상 state) 도 삭제 — REJECTED 는 영구 거부, 폴링 의미 X. `_load_states` (poll.py) 가 marker 형제 sibling 검사 안 하는 한 stale state 가 폴링되는 사고 차단.

### F-4. `scripts/register.py:_save_bug` (#5)

신규 추가:
- `.FAILED.json` 제거 (BUG 가 hand-config triage 영역 *아니므로* — bug-fix workflow 영역)
- `_prune_triage_queue(slug)` 호출 (dashboard `/triage/failed` 에 stale 표시 차단)
- `.REJECTED.json` 은 *건드리지 X* — marker_kind 우선순위가 처리 (rejected > bug). REJECTED 이미 final 결정.

### F-5. `scripts/register.py` rc=3 manual paths (#6)

`_single_article_nav_only_check` (L1289) + `_board_shape_check` (L1332) 의 `_learn_pattern(...)` 호출을 `_save_rejected(slug, url, reason, note="gate: <name>", learn=True)` 로 교체. `_save_rejected` 가 내부에서 `_learn_pattern` 호출 (learn=True) — 중복 X.

`_meta_article_diverging_check` (L1303) + `_multi_host_hub_check` (L1317) 은 이미 `_save_rejected` 호출 — 그대로 (learn=False, 보드/article 같은 first segment 위험).

### F-6. `bot/worker.py` rc=3 분기 (#6 후속)

register 가 4 rc=3 분기 모두 `_save_rejected` 로 구체적 reason 의 REJECTED 마커 박으므로 worker 의 generic-reason `_save_rejected` 가 *덮어쓰지* 않도록 marker 없을 때만 fallback (defensive):

```python
if not (_STATE_DIR / f"{slug}.REJECTED.json").exists():
    _save_rejected(slug, url, reason="rc=3 fallback (register 내 marker 박힘 실패 — generic 거부 사유)", ...)
```

### F-7. `tests/state_lifecycle/test_marker_lifecycle.py` 신규 — 3 회귀 테스트

1. `save_rejected_cleans_siblings`: .FAILED + .BUG + <slug>.json 다 제거 + .REJECTED 만 남음
2. `save_bug_clears_failed_keeps_rejected`: .FAILED 제거 + queue prune + .REJECTED 보존
3. `migrate_preserves_marker_suffix`: build_mapping stem 추출 정확 + rename_state 가 4 suffix 모두 same-suffix 로 rename

각 test 가 tempfile 로 isolated state_dir. `_learn_pattern` / `_prune_triage_queue` monkey-patch — 외부 자원 없이.

### F-8. `scripts/probe_smoke.py`

`EXTRA_UNIT_TEST_DIRS` 에 `tests/state_lifecycle` 추가 → smoke stage 5 가 자동 실행.

## 영향

- **사용자 향**: 변화 X (REJECTED 메시지 등 동일).
- **운영자 향**:
  - dashboard `/triage/failed` 일관성 강화 — BUG/REJECTED 전환 시 FAILED 잔재 X.
  - `migrate_slug_schema.py` 안전성 critical 강화 — 옛 코드는 `.REJECTED` 슬러그를 등록 사이트로 위장.
  - manual `python scripts/register.py "<url>"` 직호출 후 dashboard `/cases` / `/triage` 일관성 — REJECTED marker 항상 박힘.
- **회귀 risk**:
  - `_save_rejected` 가 이제 `<slug>.json` 도 삭제 — 이전에 등록 성공한 slug 가 REJECTED 되면 state 손실. 의도된 동작 (REJECTED = 영구 거부, state 무의미). 만약 unreject 가능성 있는 케이스에서 `_clear_rejected` 호출하면 state 다시 만들어야 함 — 기존 흐름과 동일.
  - `_save_bug` 가 FAILED 제거 — FAILED 상태에서 BUG 로 전환 시 옛 진단 정보 (last_feedback, last_config) 손실. `_save_bug` 의 tail 필드에 이미 register output 보존 — 정보 손실 X (실용적).

## 회귀 검증

- `python tests/state_lifecycle/test_marker_lifecycle.py` → **3 PASS** (save_rejected / save_bug / migrate).
- `python scripts/probe_smoke.py --stage 3 --stage 5` → **348 PASS / 0 FAIL** (이전 345 → +3 = 신규 fixture 3 case).
- pre-push hook 통과 확인.

## 트랙 B 매칭 (자가 점검 §6.7)

전부 F 자리 인프라 — 트랙 A (사용자/사이트 별) 없음, 트랙 B (구조 일반화) 가 전부. 7 카테고리 누락 — 모두 검토했고 finding 6건 모두 박음. deferred 후보 없음.

## 남은 정리

- N100 bot restart (bot/worker.py 변경, scripts/register.py 변경 — bot 이 subprocess 호출하지만 import 캐시 있을 수 있음).
- N100 의 기존 BUG/REJECTED marker 가 사이드 effect 로 stale FAILED/state 가지고 있을 수 있음 — 다음 사용자 trigger 시 새 fix 가 자동 정리.
