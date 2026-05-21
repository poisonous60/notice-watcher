---
slug: infra_worker_rc4_triage_double_record_2026-05-21
url: (인프라 case — 특정 사이트 X. 트리거 = batch 후 triage queue 오염 진단)
status: 🏗 인프라 (bot/worker rc=4 분기 append_triage_queue 중복 제거 + append dedup)
outcome: improved
date: 2026-05-21
fix_layer: F
failure_keys: [triage_queue_dashboard_mismatch, rc4_double_record, queue_noise, soft_404_queue_pollution]
config_strategy:
adapters_changed:
engine_files_touched: [bot/worker.py, bot/site_ops.py, messages/worker_url_dead.txt]
tags: [self-improvement, bot-worker, triage-queue, url-dead, soft-404, dashboard-mismatch, recurrence]
requested_by: 운영자 (2026-05-21-anime batch 후 triage 큐에 soft-404/content/url_dead 가 섞여 다음 batch 에 이중으로 보임)
---

## 트리거

운영자: "batch 하면서 실패한 게 triage 큐에 들어가는데 soft-404·content 오탐·실제 list page 실패가 섞여서, 다음번에 이중으로 본다. 조사하고 이중 안 되게 해줘."

## 진단

N100 `output/triage_queue.jsonl` 99줄 / 94 고유 slug. poll_state 마커로 분류:
- **REJECTED 44** = 이미 거부됨 (url_dead/soft-404/policy/board_shape) — work 큐에 있으면 안 됨 (오염)
- FAILED(work) 49 = 진짜 hand-config 대상
- 중복(>1줄) slug 3 (같은 사이트 반복 실패가 줄 누적)

## 근본 원인 — 2026-05-17 rc=2 버그의 rc=4 재발

`[[infra_worker_rc2_triage_double_record_2026-05-17]]` 에서 rc=2/3 은 "register 가 `_save_rejected`
→ `.REJECTED.json` + `_prune_triage_queue` 마친 뒤 worker 가 다시 `append_triage_queue` 부르면
prune 직후 re-add" 라 append 안 하게 고쳤음. 그런데 **2026-05-20/21 url_dead(rc=4) split 이
rc=2 에서 갈라져 나오면서**, worker.py 의 rc 분기(rc=3 / rc=2 / rc∈(-1,-2,-3) / else)에서
**rc=4 가 누락** → `else` → `append_triage_queue` 로 re-add. register 는 rc=4 도 `_save_rejected`
→ `_prune_triage_queue` 하므로(soft_404/target_not_found/cert_or_dns_broken), worker 의 re-add 가
정확히 같은 오염. soft-404 게이트(2026-05-21 `[fix-layer: C+F] track-B`)로 soft-404 가 rc=4 로
잡히기 시작하면서 노출 폭 증가.

추가: `append_triage_queue` 가 순수 append 라 같은 slug 반복 실패 시 줄 누적 (dedup 없음).

## 수정

1. **bot/worker.py** — `elif rc == 4:` 분기 추가 (rc=2/3 와 동일하게 append 안 함, `worker_url_dead`
   메시지). register 가 이미 REJECTED + prune.
2. **bot/site_ops.py** — `append_triage_queue` 가 같은 slug 기존 줄 제거 후 1줄로 교체 (slug 당 최대 1줄,
   최신 실패만). 반복 실패 줄 누적 = 이중 방지.
3. **messages/worker_url_dead.txt** — rc=4 사용자 메시지 신규 (해요체).
4. **데이터 정리** — N100 큐 99→49 (stale REJECTED 45 제거, backup `triage_queue.jsonl.bak-20260521`).
   local 동기.

## 검증

- `python -m py_compile bot/worker.py bot/site_ops.py` PASS
- `render('worker_url_dead', slug='X')` 정상 출력
- N100 큐: 99→49 (FAILED work item 만, dedup)
- 향후: rc=4 거부는 register 의 prune 으로만 남고 worker re-add 없음 → dashboard `/triage/failed`
  (`.FAILED.json` source) 와 `triage.py list`(queue source) 일치.

## 일반화 (track B)

rc=2(2026-05-17)·rc=4(이번) 둘 다 "register prune 후 worker re-add" 동형. 향후 새 거부 rc 추가 시
worker.py 거부 분기에 *append 제외* 를 같이 박아야 함 — `_save_rejected` 거치는 모든 rc 는 worker 에서
append 금지가 규칙. (rc=5 capability_blocked 는 `_save_failed`=FAILED 라 work 큐 유지가 맞음 — append O.)
