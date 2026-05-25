# ADR 0019 다음 세션 인계 프롬프트

다음 세션에서 `/goal` 으로 붙여넣을 self-contained prompt. Phase 1 + Phase 2 구현.

`docs/adr/0019-unified-jobs-queue.md` 가 master spec. codex 1차 review NEEDS-CHANGE 다 반영 끝.

---

## 다음 세션 프롬프트 (붙여넣기)

```
ADR 0019 (chromium 작업 unified jobs queue) 구현. 2026-05-25 incident 후속의 마지막 항목.

## 컨텍스트 (자동 로드됨, 다시 안 묻기)

- main HEAD 에 `docs/adr/0019-unified-jobs-queue.md` (codex 1차 review NEEDS-CHANGE 반영 끝, codex 2차
  검토는 다음 세션 시작 시 별도 결정).
- ADR 0017 (poll/notify runs 추적) + ADR 0018 (cron×commit race wrapper) 배포 완료. N100 정상.
- 메모리 자동 로드: feedback-codex-delegate-use-handoff (Agent codex-rescue 금지, codex_handoff.py
  + codex_watch.py --loop 만), feedback-commit-auto-deploy (n100_deploy.sh wrapper auto deploy),
  CLAUDE.md §9.0 (worktree 의무).

## 작업 (순서)

### Phase 1 (1 commit, ~50 줄, 즉시 봉합)

목표: chromium 작업 cross-process 직렬화. semantic 변경 X.

worktree 진입: `bash scripts/session_start.sh adr0019-phase1`.

ADR 0019 §2 Phase 1 그대로:
1. `scripts/poll.py` 의 chromium 사이트 분기에서 `_chromium_lock.acquire(slots=1)` 잡음.
2. lock 잡기 = `_site_with_timeout` 의 `wait_for` *밖* + `sem_chromium` *안*. ordering:
   sem → flock → wait_for(_process_site) → finish.
3. `poll_site_runs` 새 컬럼 `lock_wait_ms` (별도 측정). `duration_ms` = fetch (wait_for 안) 그대로.
4. `poll_site_runs.status` CHECK 에 `'chromium_lock_timeout'` 추가. ADR 0017 의
   `_migrate_runs_status_enum` 패턴 재사용.
5. 새 setting `settings.poll.chromium_lock_wait_budget_s` (default 300s).
6. 새 trace span `poll.chromium_flock_acquire`.
7. 단위 테스트 `tests/scripts/test_chromium_lock_share.py` (Linux 만, Windows skip) — 두 process race.
8. codex review (`scripts/codex_handoff.py generic --task-file output/codex_phase1_review.txt
   --launch` + `codex_watch.py --loop`). NEEDS-CHANGE 다 반영.
9. probe_smoke --stage 3 --stage 5 PASS.
10. commit + push (pre-push hook 자동) + N100 auto deploy (feedback-commit-auto-deploy).
11. 1주 운영 후 `poll_runs.duration_ms` p95 + `poll_site_runs.lock_wait_ms` 분포 측정.

### Phase 2 (별도 commits, ~2-3 일, generic queue + barrier)

ADR 0019 §2 Phase 2 그대로. 핵심:

#### 2a. generic jobs schema (CRITICAL)
- `jobs.kind` CHECK 에 `'poll_site'`, `'deliver_target'` 추가.
- `jobs.url`/`slug` NULL 허용.
- 신규 컬럼: `payload_json TEXT`, `dedupe_key TEXT` + `UNIQUE INDEX idx_jobs_dedupe`.
- `_migrate_check_enum` generic 함수 추출 (ADR 0017 의 `_migrate_runs_status_enum` 패턴).
- migration test 必 (옛 fixture → connect → enqueue 새 kind 성공).

#### 2b. worker 분기 (HIGH)
- `_process_job` 을 kind-별 dispatcher 로 refactor. register-only guards 를 'register'/'reprobe'
  분기 안으로 이동.
- 새 핸들러: `_process_poll_site`, `_process_deliver_target`.
- `engine/poll_one.py` (또는 `scripts/poll_core.py`) 모듈 추출 — cron 의 httpx path + worker 의
  chromium path 공유 (ADR 0017 의 `_fetch_one` + persist 검증 로직).

#### 2c. delivery freshness barrier (CRITICAL)
- `_process_deliver_target` 진입 시 `db.poll_run_blocking_for_today(today_kst)` 검사.
- "오늘 가장 최근 poll_runs 의 모든 child poll_site_runs 가 terminal 도달?"
  False = job pending 유지 + N초 뒤 재시도. True = 정상 진행.
- `poll_runs.status` 추가 enum: `'enqueue_done'` (cron 종료, worker 처리 대기) → `'done'` (모든
  child terminal).

#### 2d. deliver_target idempotence (HIGH)
- `dedupe_key='deliver:{kind}:{id}:{today_kst}'` UNIQUE.
- 봇 1분 tick 이 매분 enqueue 시도해도 INSERT OR IGNORE.

#### 2e. poll.py + delivery_tick 변경
- chromium 사이트: enqueue 만 + dedupe_key='poll:{run_id}:{slug}'.
- httpx 사이트: cron inline 유지. routing predicate = `_uses_chromium(config)`.
- 봇 1분 tick: `enqueue_job(kind='deliver_target', dedupe_key=...)`.
- `scripts/deliver_due.py` = dev/CLI 보존. `flush_target` = shared service (worker + CLI 공유).

#### 2f. worker capacity 정책 (HIGH — 사용자 결정 필요)
- 첫 안: pool_size=2 + slot 1 은 priority<2 (user/reprobe) 전용 reserve.
- 또는: pool_size=2 + strict priority + chromium_lock.slots=1.
- 시작 시 사용자 의견 받기. ADR 0019 §2g.

#### 2g. priority canonical 표 (HIGH)
0=user > 1=reprobe > 2=deliver_target > 3=poll_site > 4=batch-retry > 5=batch.
`_derive_priority(kind, via)` 갱신 + 기존 pending row 백필.

#### 2h. runs ↔ jobs cross-link (HIGH)
`poll_site_runs.job_id INTEGER NOT NULL REFERENCES jobs(id)` 신규 컬럼.
- result master = `poll_site_runs.status`.
- lifecycle master = `jobs.status`.
- dashboard `/runs/poll/{id}` ↔ `/jobs/{job_id}` 양방향 link.

### 검증 게이트 (Phase 2)
- migration test: 옛 jobs 테이블 fixture → enqueue 새 kind 성공.
- priority ordering test: 0/1/2/3/4/5 dequeue 순서.
- delivery barrier test: poll_runs.status='enqueue_done' + child pending → deliver wait.
- duplicate enqueue test: 같은 dedupe_key 재시도 → INSERT OR IGNORE.
- worker restart test: reset_running_to_pending + INSERT OR IGNORE idempotent.
- fairness 측정: user register p95 wait time.

## 사용자 결정 필요 (Phase 2 시작 전)

1. **worker capacity**: pool_size=2 + slot reserve (interactive 보호) vs pool_size=2 + strict
   priority only. ADR §2g.
2. **첫 codex 검토 의 NEEDS-CHANGE 반영 ADR 의 2차 검토 받을지 (Phase 2 시작 전)**: 시간 비싸지만
   ADR 이 다음 세션의 기반 — 1차 NEEDS-CHANGE 의 깊이로 봐서 2차도 가치 있음.
3. **Phase 2 sub-commits 분리 정책**: 한 commit = (a) schema 마이그 + dedupe_key, (b) worker
   분기 추가, (c) poll.py enqueue 변경, (d) delivery barrier, (e) tick enqueue. 각각 prove 가능.

## 산출물

- Phase 1 commit (`scripts/poll.py` + `bot/db.py` 의 lock_wait_ms 컬럼 + chromium_lock_timeout
  enum + `_chromium_lock.acquire` 통합 + 테스트).
- Phase 2 commits (~5 개 분리, ADR 0017 처럼 ADR 1회 + codex 2-3차 review 받기).
- 영구 게이트 박기 (CLAUDE.md §10 의 ADR 0019 ref 만 추가).

## 시작

1. 이 프롬프트 자체로 컨텍스트 충분.
2. 사용자 결정 3 개만 시작 시 묻기.
3. ADR 0019 spec = `docs/adr/0019-unified-jobs-queue.md`.
4. codex 1차 review 결과 = `output/codex_adr0019_review_task.result.md` (NEEDS-CHANGE 다 반영됨).
```

---

## 사용 방법

다음 세션에서 `/goal` 입력 후 위 코드 블록을 그대로 붙여넣기.

## 참고

- 본 ADR: `docs/adr/0019-unified-jobs-queue.md` (codex 1차 review 반영 rewrite 완료)
- codex 1차 review: `output/codex_adr0019_review_task.result.md`
- 관련: ADR 0006 / 0009 / 0016 / 0017 / 0018
- 2026-05-25 incident: `docs/2026-05-25-user-notify-end-to-end-incident.md`
