# ADR 0019 — chromium 작업 unified jobs queue (poll/notify ↔ register/reprobe 통합)

작성: 2026-05-25
상태: draft (codex 1차 review NEEDS-CHANGE → rewrite — CRITICAL 3 + HIGH 6 + MED 5 + LOW 3 적용)
관련: ADR 0009 (job-claim-priority), ADR 0017 (runs 추적), ADR 0006 (per-user delivery), ADR 0016 (per-site isolation)

## 1. Context

ADR 0017 이 *추적 (visibility)* 박았지만 사용자 원 요청 = *jobs 큐 통합*. 1차 codex review 가 "A=runs tracking only 권고, jobs 큐 통합은 scope creep" 라 ADR 0017 §3 의 "비-결정 (다음 ADR 후보)" 로 미뤘다 — 이 ADR 이 그 후속.

### 현재 chromium 작업 sources

| source | 직렬화 | 우선순위 |
|---|---|---|
| `bot/worker.py` (register/reprobe) | `scripts/_chromium_lock.py` fcntl flock (slots=N capacity limiter, **단순 mutex 아님**) | ADR 0009 priority queue |
| `scripts/poll.py` (cron 폴링) | `asyncio.Semaphore(1)` — in-process only | 없음 |
| `scripts/deliver_due.py` (봇 1분 tick) | chromium 안 씀 | n/a |

**문제**: poll cron (08:20) + user `/watch` 동시 = 두 프로세스 chromium 동시. RAM 충돌 + 같은 사이트면 cookie/IP 충돌.

### codex 1차 review 의 5 가지 핵심 우려 (CRITICAL/HIGH 통합)

1. **Phase 1 flock invariant** — wait_for 밖에서 flock 잡으면 poll 의 180s wall timeout 발동 안 함 → register hang 시 poll 사이트가 systemd 외각 timeout 까지 무한 대기 가능. 별도 lock_wait budget + status 분리 必.
2. **Phase 2 의 freshness barrier** — 08:20 poll enqueue + 08:30 delivery. `deliver_target` priority 가 `poll_site` 보다 빠르면 poll 진행 중에 발송 → 2026-05-25 incident 재현. delivery 가 poll 완료 보장 必.
3. **jobs 테이블 register-centric** — `url/slug NOT NULL`, `dedupe(kind,slug)`, worker 가 register guards. `deliver_target` 은 url/slug 없음. generic schema 必 — `payload_json`, `dedupe_key`, nullable.
4. **chromium_lock.slots semantics** — slots≥2 = capacity limiter, mutex 아님. Phase 1 의 "직렬화" 주장은 slots=1 명시 필요.
5. **worker pool 의 작업 다양화** — register(interactive 30s) + poll_site(chromium 5-180s) + deliver_target(LLM-heavy 10-60s) 한 pool. interactive 보호 必.

## 2. Decision

**2 단계 마이그**. Phase 1 = 즉시 봉합 (RAM 충돌만), Phase 2 = jobs 큐 통합 (priority + barrier).

### Phase 1 (1 commit, ~50 줄) — flock 공유 + lock_wait 분리

목표: chromium 작업 cross-process 직렬화. semantic 변경 X.

#### 변경:
- `scripts/poll.py` 의 chromium 사이트 fetch 가 `_chromium_lock.acquire()` 잡음. register.py 와 같은 file lock 공유.
- **slots = 1** 명시 (Phase 1 운영 동안). slots≥2 는 capacity limiter 의미라 진짜 직렬화 아님 — 사용자 요청 명확히 직렬화 = 1.
- `_site_with_timeout` 의 ordering (codex CRITICAL §1 — 4 stage 분리):
  ```
  1. sem 대기 (asyncio.Semaphore — in-process, fast)            : not measured, not in wall budget
  2. flock 대기 (_chromium_lock.acquire — cross-process)        : lock_wait_ms (측정 분리)
                                                                  budget = `poll.chromium_lock_wait_budget_s` = 300s default
                                                                  초과 = status='chromium_lock_timeout' (새 enum)
  3. wait_for(_process_site, timeout=POLL_SITE_TIMEOUT_S=180s)  : fetch_duration_ms
                                                                  초과 = status='poll_timeout' (기존)
  4. finish — lock 풀고 sem 풀고 returns
  ```
- `poll_site_runs` 새 컬럼: `lock_wait_ms INTEGER`. 기존 `duration_ms` = fetch (wait_for 안). 둘 분리.
- `poll_site_runs.status` CHECK 에 `'chromium_lock_timeout'` 추가. ADR 0017 의 `_migrate_runs_status_enum` 패턴 재사용.
- 새 trace span `poll.chromium_flock_acquire`. dashboard `/timings` 가시화.
- `asyncio.Semaphore(sem_chromium)` 유지 (안전망 + Windows fallback — `_chromium_lock` 이 Windows 에서 no-op).
- 새 setting `settings.poll.chromium_lock_wait_budget_s` (default 300, env override).

#### 위험·완화:
- `register subprocess hang` (chromium_lock 영구 보유) → poll 사이트 모두 chromium_lock_timeout 으로 죽고 진행 (poll wall 영향 X). 5분 lock-wait budget 이 적정 — register 정상 30s, 비정상 hang 시 poll 다음 cron 까지 미루기 OK (daily).
- `lock_wait` 시간 = poll 총 시간 증가. anti-bot 30s × 7 사이트 직렬 = 3.5분. systemd `TimeoutStartSec=1200` 안에 들어옴.
- `_chromium_lock.acquire` 가 *호출 위치* — `_process_site` 안 (chromium 사이트만) 또는 `_site_with_timeout` 안? codex CRITICAL §1 룰에 따라 *_site_with_timeout 의 wait_for 밖* + sem 안 (sem 대기 후 flock).

#### Phase 1 검증:
- Linux flock 단위 테스트 (`tests/scripts/test_chromium_lock_share.py` 신규) — 두 process 가 같은 lock file 잡는 race 확인.
- 손-poll + 동시 register batch → journal 에 `[poll] chromium_flock_acquire t=Xms` 가시화.
- 1주 운영 후 `poll_runs.duration_ms` p95 측정 + `poll_site_runs.lock_wait_ms` 분포.

### Phase 2 (별도 commits, ~2-3 일) — generic jobs queue + 발송 barrier

목표: bot worker daemon 이 모든 chromium 작업 + delivery 처리. priority 통합 + 발송 freshness barrier.

#### 2a. generic jobs schema (codex CRITICAL §3)

```sql
-- jobs 테이블 rebuild — register-centric → generic.
-- ADR 0017 의 _migrate_runs_status_enum 패턴 재사용 (generic _migrate_check_enum 으로 추출).
ALTER:
  kind        CHECK 추가: 'poll_site', 'deliver_target' (기존 'register','reprobe' 유지)
  url         NULL 허용  (deliver_target 은 url 없음)
  slug        NULL 허용  (deliver_target 은 slug 없음)
  payload_json TEXT NULL — kind 별 sub_payload (poll_site = {slug,url,config_path,page_size,...},
                          deliver_target = {target_kind,target_id,today_kst,run_id,...})
                          sub_payload 기존 컬럼 재사용도 OK — 컬럼명 검토.
  dedupe_key  TEXT NULL — UNIQUE index 박음. poll_site = 'poll:{run_id}:{slug}',
                          deliver_target = 'deliver:{target_kind}:{target_id}:{today_kst}'.
                          register/reprobe 는 dedupe=True 일 때 enqueue 가 채움 (kind:slug 형식).

CREATE UNIQUE INDEX idx_jobs_dedupe ON jobs(dedupe_key) WHERE dedupe_key IS NOT NULL;
CREATE INDEX idx_jobs_kind_status ON jobs(kind, status, id);
```

마이그 = `migrate_jobs_kind_enum(conn, table='jobs', probe='poll_site', new_create=_JOBS_REBUILD)`.
ADR 0017 패턴 그대로 + 컬럼 추가도 함께 (`payload_json`, `dedupe_key`). 기존 row 의 dedupe_key 는 backfill (`kind || ':' || slug`).

#### 2b. worker 분기 (codex HIGH — kind 별 dispatch 분리)

`bot/worker.py` 의 `_process_job` 을 kind-별 dispatcher 로 refactor. register-only guards (slug/url NOT NULL 검사 등) 를 kind='register'/'reprobe' 분기 *안* 으로 이동.

```python
def _process_job(job):
    if job.kind in ("register", "reprobe"):
        return _process_register_reprobe(job)  # 기존 path 거의 그대로
    if job.kind == "poll_site":
        return _process_poll_site(job)         # 새 path
    if job.kind == "deliver_target":
        return _process_deliver_target(job)    # 새 path
    raise ValueError(f"unknown kind: {job.kind}")
```

- `_process_poll_site`: payload_json 에서 slug/url/config_path 추출 → `_chromium_lock.acquire(slots=1)` → ConfigAdapter fetch → posts upsert + persist 검증 (ADR 0017 의 `_fetch_one` + invariant 그대로) → `poll_site_run_finish`. 코어 로직은 `engine/poll_one.py` (또는 `scripts/poll_core.py`) 신규 모듈로 추출해서 cron 의 httpx path 와 공유.
- `_process_deliver_target`: payload_json 에서 target_kind/target_id 추출 → `scripts/deliver_due.flush_target` (이 함수가 shared service 로 retained, codex HIGH §6) → `notify_target_run_finish`. chromium_lock 안 잡음 (LLM/Discord 별).

#### 2c. delivery freshness barrier (codex CRITICAL §2)

**문제**: 08:20 cron 이 chromium 사이트들 enqueue → 08:30 delivery_tick 이 deliver_target enqueue. priority 2 > 3 이라 deliver_target 이 먼저 dequeue → poll 진행 중 발송 → 2026-05-25 incident 재현.

**해법**: delivery 가 *해당 day 의 active poll_runs 가 terminal 도달할 때까지 wait*. 구체:

옵션 A (single barrier function — 추천):
- `_process_deliver_target` 진입 시 `db.poll_run_blocking_for_today(conn, today_kst)` 호출.
- "today_kst 의 가장 최근 poll_runs 가 있고, 그 run 의 모든 child poll_site_runs 가 terminal (ok/error/poll_timeout/persist_mismatch/chromium_lock_timeout 등) 도달했는가?" 검사.
- False 면 job 을 `status='pending'` 으로 유지 + 새 `requeue_at` 컬럼 박아 N초 뒤 재시도 (또는 sleep + retry). 정상 30초 안 끝남.
- True 면 정상 처리.

옵션 B (priority preemption):
- `deliver_target` 이 priority 4 (poll_site 보다 낮은) → poll_site 가 먼저. fairness 위반 (interactive 발송이 cron 뒤로 밀림).

**선택 = 옵션 A (barrier)**. priority 는 fairness 의도대로 유지, barrier 가 dependency 표현.

`poll_runs.status='done'` semantics 도 갱신 (codex MED §1):
- `running` = 폴링 cron 진행 중 (httpx fetch + chromium enqueue 진행 중).
- `enqueue_done` = cron 종료, chromium worker 처리 대기. (새 status enum)
- `done` = 모든 child poll_site_runs 가 terminal 도달.
- `crashed` / `killed` = reaper.

barrier 가 `enqueue_done` 또는 `running` 이면 wait, `done` 이면 진행.

#### 2d. deliver_target 의 idempotence (codex HIGH §4)

`dedupe_key='deliver:{kind}:{id}:{today_kst}'` UNIQUE → 같은 (kind, id, day) 1회만. 봇 1분 tick 이 매 분 enqueue 시도해도 INSERT OR IGNORE 라 첫 번째만 박힘. 처리 완료 후 status='done'/'failed' 으로 가지만 dedupe_key 는 그날 유지 — 다음 날 새 dedupe_key.

`enqueue_job` 의 `dedupe=True` 가 같은 dedupe_key 보면 기존 job_id 반환 (기존 register dedupe 패턴 확장).

#### 2e. `scripts/poll.py` 변경

- chromium 사이트: `enqueue_job(kind='poll_site', dedupe_key=f'poll:{run_id}:{slug}', payload_json={...})` 만.
- httpx 사이트: cron 안 inline 처리 유지 (빠른 작업, codex MED §2 의 promotion path 명시 — `_uses_chromium(config)` 가 단일 routing predicate, future 어느 사이트가 strategy 바뀌면 자동 jobs 로 라우팅).
- cron 종료 시 `poll_runs.status='enqueue_done'` (chromium worker 처리 대기). worker 가 마지막 child 박을 때 status='done' 전이 (또는 별도 background loop 가 검사 — 단순화 위해 worker 가 update).

#### 2f. `bot/delivery_tick.py` 변경

- 봇 1분 tick 이 `deliver_due.py` subprocess 띄우는 대신 `enqueue_job(kind='deliver_target', dedupe_key=...)` 만.
- `scripts/deliver_due.py` = **dev/CLI 보존** (codex HIGH §5). `--force-target`, `--dry-run`, `NOTIFY_TEST_TARGETS` 같은 dev 도구 그대로. `flush_target` 함수가 shared service — worker 와 CLI 둘 다 호출.
- production 봇 1분 tick 의 enqueue 가 `NOTIFY_TEST_TARGETS` env 받으면 worker 가 그 env 받게 — 또는 payload_json 에 `test_skip` 플래그. 일단 production path 는 test 안 함 (test 는 CLI 만).

#### 2g. worker capacity 정책 (codex HIGH §3)

```
pool_size = 2
  slot 1 = priority < 2 전용 (user register=0, reprobe=1) — interactive lane
  slot 2 = 모든 priority (mixed lane)
```

또는 더 간단:
```
pool_size = 2
chromium_lock.slots = 1 (chromium 작업 직렬화 — slot 2 개라도 동시 chromium X)
slot reserve 없음 — strict priority 만. 단점: chromium 사이트 30s × N 가 user register 막을 수 있음.
```

**v1 (codex 권고)** = 첫 안 (slot reserve). 마이그 후 1주 운영 후 fairness 측정 → 조정.

#### 2h. priority 통합 (canonical 표, codex HIGH §2)

```
0 = user (via='watch'|'preview') — interactive
1 = reprobe (kind='reprobe')
2 = deliver_target (kind='deliver_target')                                     — 시간 민감
3 = poll_site (kind='poll_site')                                              — cron
4 = batch-retry (via='batch-retry')                                           — 기존 ADR 0009
5 = batch (via='batch')                                                       — 기존 ADR 0009
```

마이그 시 `_derive_priority(kind, via)` 갱신 + 기존 row 백필:
```sql
UPDATE jobs SET priority = CASE
    WHEN via='batch' THEN 5
    WHEN via='batch-retry' THEN 4
    WHEN kind='reprobe' THEN 1
    ELSE 0 END
WHERE status IN ('pending','running');
```

#### 2i. runs ↔ jobs SoT (codex HIGH §7)

- `poll_site_runs.job_id INTEGER NOT NULL REFERENCES jobs(id)` — Phase 2 schema 의 필수.
- contradiction 룰:
  - poll **result** (ok / persist_mismatch / breakage) = `poll_site_runs.status` 가 master.
  - job **lifecycle** (pending / running / done / failed) = `jobs.status` 가 master.
  - dashboard `/runs/poll/{id}` 가 둘 다 link + 둘 다 status 표시.

### 2j. 비-결정 (Phase 2 의 sub-결정)

- **httpx 사이트도 jobs 로?** — 빠른 작업 (~1s) 분리 유지. routing predicate = `_uses_chromium`.
- **owner DM 알림** — ADR 0017 §3 의 비결정 그대로. Phase 2 후 별도 ADR.
- **deliver_target 의 worker 안 LLM 호출 — bot 봇 RAM 영향** — 측정 후 결정.

## 3. Consequences

### 긍정 (Phase 1)
- RAM/cookie 충돌 즉시 봉합. 50 줄 commit.
- `lock_wait_ms` 분리 측정으로 운영 데이터 누적.

### 긍정 (Phase 2)
- chromium 작업 single source. dashboard `/jobs` 가 모든 chromium 작업 visible.
- priority 통합 + barrier — interactive (user) 보호 + 발송 freshness 보장.
- runs ↔ jobs cross-link.
- bot event loop 더 simple (deliver subprocess → enqueue 만).
- generic jobs schema = future kind 추가 (예: scheduled task) 자유.

### 부정
- Phase 1: lock_wait 시간 = poll wall clock 증가.
- Phase 2: schema 마이그 = bot.sqlite3 의 jobs 테이블 rebuild. ADR 0017 패턴 재사용으로 위험 낮음.
- worker capacity 정책 결정 = 운영 데이터 필요.
- delivery barrier = 첫 deploy 직후 며칠은 wait 실측 필요. 정상 30s 안 끝나지만 chromium hang 시 deliver 같이 지연.

## 4. 영구 게이트 (CLAUDE.md §8a)

이 ADR + `bot/worker.py` 의 kind 분기 + `scripts/poll.py` 의 enqueue + `bot/db.py` 의 jobs CHECK + dedupe_key + `bot/delivery_tick.py` enqueue + delivery barrier = 영구 게이트.

동시에:
- `scripts/poll.py` docstring 에 Phase 1 flock + Phase 2 enqueue 흐름.
- `bot/worker.py` 의 kind 분기 위 주석에 ADR 0019 ref.
- `CLAUDE.md §10` 에 ADR 0019 ref.
- 단위 테스트 (codex LOW §3): migration / priority ordering / delivery barrier / duplicate enqueue / lock_wait 측정.

## 5. 검증

### Phase 1
- `tests/scripts/test_chromium_lock_share.py` — Linux 만, 두 process 가 같은 lock file 잡는 race 확인 + lock_wait_ms 측정.
- pre-push hook `probe_smoke --stage 3 --stage 5`.
- 손-poll + 동시 user `/preview` 트리거 → journal 의 `chromium_flock_acquire` 직렬화 + `lock_wait_ms` 박힘.
- 1주 운영 후 p95 측정.

### Phase 2
- **migration test** (codex HIGH §5 의무): 옛 jobs 테이블 fixture → connect → `_migrate_jobs_kind_enum` 동작 → `enqueue_job(kind='poll_site')` 동작 → 옛 register row 유지.
- **priority ordering test**: 0/1/2/3/4/5 enqueue 후 claim 순서.
- **delivery barrier test**: `poll_runs.status='enqueue_done'` + child pending → `_process_deliver_target` 가 wait. 모든 child terminal → 진행.
- **duplicate enqueue test**: 같은 dedupe_key 재시도 → 두 번째 INSERT OR IGNORE → 첫 job_id 반환.
- worker 죽었다 살아도 미완 job 들이 `reset_running_to_pending` 으로 재처리. `poll_site` 재시도 시 같은 `run_id` 재사용 + INSERT OR IGNORE (UNIQUE(run_id, slug)) idempotent.
- pool_size=2 + slot reserve 의 fairness 측정 — user register p95 wait time.
- worker daemon 죽었을 때 cron 의 enqueue 만 진행, deliver 도 enqueue. 봇 살아나면 자동 처리.

## 6. 향후

- Phase 1 commit → 1주 운영 → Phase 2 진행 결정.
- Phase 2 후 worker pool_size / slot reserve 정책 조정.
- owner DM 알림 (별도 ADR).
- httpx 사이트도 jobs 통합 검토 (Phase 2 운영 후).
