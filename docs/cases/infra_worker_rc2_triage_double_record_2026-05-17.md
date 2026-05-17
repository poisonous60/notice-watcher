---
slug: infra_worker_rc2_triage_double_record_2026-05-17
url: (인프라 case — 특정 사이트 X. 트리거 = triage queue 잡음 진단)
status: 🏗 인프라 (bot/worker rc=2 분기 append_triage_queue 중복 호출 제거)
outcome: improved
date: 2026-05-17
fix_layer: F
failure_keys: [triage_queue_dashboard_mismatch, rc2_double_record, queue_noise]
config_strategy:
adapters_changed:
engine_files_touched: [bot/worker.py]
tags: [self-improvement, bot-worker, triage-queue, policy-reject, dashboard-mismatch]
requested_by: 운영자 (FAILED 큐 처리 후 dashboard 와 triage list 불일치 발견)
---

## 트리거

운영자 질문: "triage 큐에 아직 남아있는데 / 남아있는 것들은 뭐야? dashboard에는 안 뜨는데"

진단 — `triage.py list` 19건 vs dashboard `/triage/failed` 7건 불일치:
- **F=y 7건** = `*.FAILED.json` 활성 마커 (dashboard 가 보는 단일 source)
- **F=- 12건** = `triage_queue.jsonl` 에만 있고 `.FAILED.json` 없음 (`.REJECTED.json` 은 N100 에 존재 = 이미 거부 처리)

12건 다 동일 패턴: `[register] ❌ 등록 거부 (위 사유)` (policy_check 거부, rc=2) + N100 의 `.REJECTED.json` 마커 존재 + learned_blacklist 학습됨.

## 근본 원인

`bot/worker.py:312-318` rc=2 분기:

```python
elif rc == 2:
    append_triage_queue(url, slug, job["via"], req_by, tail)  # ← 잡음 원천
    await edit_channel_message(...)
```

`register.py` 의 흐름:
1. `_policy_check` 또는 `_meta_article_diverging_check` 또는 `_multi_host_hub_check` 가 거부 결정
2. `_save_rejected(slug, url, ...)` 호출 → `.REJECTED.json` + learned_blacklist + `_prune_triage_queue(slug)` (queue 에서 이 slug 제거)
3. `return 2`
4. bot/worker 가 rc=2 받음 → `append_triage_queue` 호출 (← step 2 의 prune 직후 re-add)

결과: `.REJECTED.json` 있고 학습됨 + queue 에도 entry 남음. dashboard 는 `.FAILED.json` 만 보므로 안 뜸 → triage list 와 불일치.

(rc=3 board_shape_check 거부 분기 L298-311 은 처음부터 append_triage_queue 안 함 — "triage 큐 오염 막기 위해 안 쌓는다" 주석 있음. rc=2 도 같은 이유여야 함.)

## 픽스 (fix_layer: F — 1 파일 변경)

### F-1. `bot/worker.py` — rc=2 분기 `append_triage_queue` 제거

```python
elif rc == 2:
    # policy_check 거부 (BLOCKED/LOGIN_REQUIRED) — register 가 이미 _save_rejected →
    # `.REJECTED.json` + learned_blacklist + _prune_triage_queue 마쳤음.
    # 여기서 append_triage_queue 다시 부르면 prune 직후 re-add 라 큐 잡음 (dashboard X / triage list O 불일치).
    # rc=3 분기와 동일하게 triage 큐 오염 막기 위해 안 쌓는다.
    await edit_channel_message(...)
```

`else` 분기 (rc=1 = `.FAILED.json` 자동 등록 실패) 의 `append_triage_queue` 는 유지 — `.FAILED.json` 은 손-처리 대상이라 큐 등록이 맞음.

### F-2. 12 stale entry 일괄 prune (N100 + local)

`triage_queue.jsonl` 에서 다음 12 slug 제거:
- host_encykorea-aks-a_Contents_e87d36b0
- host_grips-ac-jp_teacher_52c26f51
- host_techethics-ieee_about_bdcbf970
- host_standardsuniver_e-magazine_0e5263ea
- host_canvas-skku-edu_courses_37eff499
- host_d4m0n-tistory-c_10_dd865fee
- host_kevin0960-tisto_entry_0e610db5
- host_webzine-aihub-o_insight_ae42b72f
- host_wiki-skullsecur_index.php_af0b507c
- host_docs-google-com_spreadsheets_68184bc3
- host_benesiaxd-tisto_2_0ac1cf17
- host_harley-hwan-git_2021-11-11-AttackLab_b6c964d8

다 N100 에 `.REJECTED.json` 마커 존재 확인 + learned_blacklist 학습 확인. queue prune 만 (마커는 그대로).

## 영향

- **사용자 향**: 변화 없음. policy 거부 받는 `/preview` 사용자에게 보내는 `worker_policy_blocked` 메시지 동일.
- **운영자 향**: dashboard `/triage/failed` 와 `triage.py list` 일치 — 두 view 같은 active FAILED 목록 표시.
- **미래 rc=2 거부**: queue append 안 됨 → 잡음 누적 X.
- **회귀 risk**: 0. rc=2 거부 정보는 `.REJECTED.json` 에 보존 (slug/url/reason/note/timestamp). 운영자 audit 필요 시 그 파일 보면 됨.

## 회귀 검증

- `python scripts/probe_smoke.py` → 319 PASS / 0 FAIL (영향 X — bot 영역).
- `python scripts/triage.py list --skip-later` → 7건 (F=y only, F=- 0건) ↔ dashboard `/triage/failed` 7건 동일.

## 트랙 B 매칭 (자가 점검 §6.7)

이 case 는 인프라 자체 — *트랙 B 가 전부*. 트랙 A (특정 사용자/사이트 향) 없음.

- **2a (인식기)**: ❌ 무관.
- **2b/2c/2d**: ❌ 무관.
- **F (엔진 코드)**: ✅ `bot/worker.py` 단일 분기.

## 남은 정리

- N100 bot restart 필요 (bot/worker.py 변경, import 캐시).
- 미래 운영자가 `triage_queue.jsonl` audit 시 — 이제 *오직 actionable FAILED* 만 들어옴.
