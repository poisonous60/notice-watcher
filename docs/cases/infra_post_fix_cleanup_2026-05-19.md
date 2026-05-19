---
slug: infra_post_fix_cleanup_2026-05-19
url: (infra — triage post-fix-cleanup + register --gate-only + digest backfill)
status: ✅ post-fix-cleanup 명령 — 영구 게이트 박은 후 N100 옛 큐 자동 정리
outcome: improved
date: 2026-05-19
fix_layer: F
failure_keys: [n100_stale_queue_after_permanent_gate, manual_cleanup_required]
config_strategy: none
adapters_changed: []
engine_files_touched: [engine/digest.py, scripts/register.py, scripts/triage.py, .claude/skills/hand-config/SKILL.md, tests/probe_heuristics/test_digest_backfill.py]
tags: [infra, post-fix-cleanup, gate-only, n100-cleanup, digest-backfill]
requested_by: poi23619
---

## 무엇이 일어났나
[[infra_root_marketing_homepage_gate_2026-05-19]] + [[infra_learned_root_only_match_2026-05-19]] 영구 게이트 박은 후 — N100 의 옛 4 FAILED.json + triage_queue.jsonl 4 라인이 **자동 cleanup X**.

원인:
- 봇 워커는 사용자 `/preview` `/watch` 명령 받을 때만 register 호출. 큐 entry 자동 재시도 X
- dev 박스 `register --reuse-probe` = dev 박스 local only — N100 영향 X
- N100 에서 register 직접 호출은 ssh + 비용 위험 (게이트 안 잡으면 LLM 4-retry)
- 옛 probe artifact 에 새 게이트 키 없을 수도 (휴리스틱 추가 후) → 게이트 안 잡힘

사용자 요청 = N100 큐 자동 정리 명령 + SKILL.md 절차 박기.

## 무엇을 박았나

### (1) `engine/digest.py:_backfill_missing_heuristics`
list_candidates.json 의 누락 휴리스틱 키 자동 보강 — 옛 artifact 호환:
```python
if "root_marketing_homepage" not in list_cands:
    list_cands["root_marketing_homepage"] = root_marketing_homepage(
        base_url=base_url,
        html_candidates=list_cands.get("html_repeating_patterns") or [],
        nav_only_same_host=list_cands.get("nav_only_same_host"),
        body_empty_likely=bool(list_cands.get("body_empty_likely") or False),
    )
```
artifact 파일 X — digest 안에만. 미래 같은 자리 휴리스틱 추가 시 같은 패턴 (한 줄 추가).

### (2) `scripts/register.py --gate-only` 새 옵션
*strict reuse + 게이트만 검사 + LLM/preflight skip*. rc 약속:
- rc=2/3: 게이트 잡힘 (기존 자리 — REJECTED + cleanup 그대로)
- rc=6: 모든 게이트 통과 — preflight + LLM skip. "수동 작업 필요" 신호
- rc=7: probe artifact 없음 — probe 새 실행 권장

자리:
- main() args 처리 직후 — artifact 검사 → rc=7
- `_try_known_platform` *skip* (gate-only 면 fetch_list 네트워크 + state.json write 회피)
- `_board_shape_check` ok 분기 직후, preflight 직전 → rc=6

비용 0 확약: probe 새 실행 X · `_try_known_platform` 네트워크/write X · preflight 네트워크 re-probe X · LLM 호출 X.

### (3) `scripts/triage.py post-fix-cleanup [--execute] [--host=<host>]`
**default dry-run** (write X, ssh X): dev 박스 snapshot artifact 로 순수 시뮬레이션. 각 FAILED 의 게이트 예측 rc 만 출력.

**--execute**: N100 ssh + 각 FAILED 의 url 에 대해 `register.py --reuse-probe --gate-only` 호출. rc 분류 + 결과 표 + summary.

ssh 실패 graceful: per-slug 'ssh_error' 표시 + N100 큐 변경 X + abort 안 함 (다른 slug 계속).

### (4) `.claude/skills/hand-config/SKILL.md` §5 step 8b 추가
영구 게이트 박는 hand-config 변경 (engine/probe/scripts/register 의 *게이트 로직* 자리) 의 N100 deploy *후* `post-fix-cleanup --execute` 호출 안내. 손-config 변경 (configs/ 만) 은 호출 X.

### (5) `tests/probe_heuristics/test_digest_backfill.py` 새 fixture (4 case)
- 옛 artifact (키 없음) → 보강 후 dict 박힘
- artifact 파일 변경 X (디스크 보존)
- 새 artifact (키 이미 있음) → 덮어쓰기 X
- 마케팅 키워드 부족 → 보강 결과 None

## 효과

- **dry-run 안전**: dev 박스에서 N100 영향 없이 큐 시뮬 (snapshot artifact read-only)
- **--execute 안전**: N100 큐의 cleanup 자동 + 비용 0 (게이트만, LLM 0)
- **미래 호환**: digest 보강 패턴으로 다음 휴리스틱 추가 시 옛 artifact 자동 호환
- **SKILL 절차**: 영구 게이트 박은 사용자가 step 8b 호출 → 옛 큐 자동 정리 + 게이트 효과 검증

## 트랙 B 자리 매핑 (§6 1번)
- (F) 새 엔진 코드 — `engine/digest.py` 보강 함수 + `scripts/register.py --gate-only` 옵션 + `scripts/triage.py post-fix-cleanup` 명령. 모두 자리 = F.
- (E/D/C/B/A) 미해당.

## 자가 점검 (§6)
1. **자리**: F (engine/scripts 코드 추가). 단일 자리.
2. **이전 케이스**: [[infra_root_marketing_homepage_gate_2026-05-19]] / [[infra_learned_root_only_match_2026-05-19]] 의 *후속 fix*. 영구 게이트 → cleanup 명령. 패턴 = "게이트 박으면 큐 cleanup 명령 함께 박는다".
3. **누구 깰까**: 0. `--gate-only` = 명시 호출만 (사용자 또는 post-fix-cleanup). 봇 워커 영향 X. 기존 rc (0/1/2/3/4) 충돌 X — 새 rc 6/7. `_try_known_platform` skip 은 gate-only 만.
4. **검증**:
   - probe_smoke stage 3+5: PASS 385 / FAIL 0 / 345 cases (이전 341 + 4 새 fixture)
   - digest_backfill fixture: 4/4 PASS
   - post-fix-cleanup dry-run smoke: CNN `/world` slug rc=6 (no match) 정확
   - design codex review v5: PASS (v1~v4 FAIL 후 보강)
5. **outcome=improved, fix_layer=F**.
6. **fixture**: `tests/probe_heuristics/test_digest_backfill.py` (4 case).
7. **트랙 B**: 매칭 — 위 §자리 F.

## 미래 후보 (deferred)
- 봇 워커 큐 주기적 재시도 (cron) — *명시 호출 (post-fix-cleanup) 보다 사용자 통제 낮음*. ADR 0003 정신과 부합 X. 본 turn deferred.
- post-fix-cleanup 의 *rc=6 slug 자동 분석* (수동 작업 가이드 출력) — 다음 turn 후보. 본 turn = cleanup 자체에 집중.
