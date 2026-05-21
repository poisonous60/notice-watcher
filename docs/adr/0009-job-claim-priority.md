# jobs 큐 우선순위 (priority queue) — 3-tier strict, stored `priority` 컬럼

## Context

N100 의 단일 `jobs` 큐를 batch(`via='batch'`) · 사용자(`via∈{watch,preview}`) · reprobe(`kind='reprobe'`, poll 이 깨진 등록사이트 자동 재-probe) 세 source 가 공유한다. `claim_next_pending` 는 `ORDER BY id ASC` (FIFO) 였다 — 그래서 batch 가 카탈로그 수백 건을 enqueue 한 직후 사용자가 `/watch` 하면 그 잡이 `id ~수백번째` 로 backlog 뒤에 줄 서서 ack 가 "수백번째 대기" 를 띄우고 실제로도 몇 시간 기다린다. 사용자는 ack 앞에서 실시간 대기하는데(가장 비싼 대기) batch 는 무인 backfill 이라 늦어도 무방하다.

hand-config 의 "시험 실행" 은 dev 박스에서 `register.py` 직접 호출 — N100 큐를 안 거치므로 이 우선순위와 무관(자연 격리). 따라서 경합은 N100 큐의 위 3 source 사이에서만 일어난다.

## Decision

`jobs.priority` INTEGER 컬럼 추가. `claim_next_pending` 의 SELECT 를 `ORDER BY priority ASC, id ASC` 로 — 작은 값이 먼저 claim. SQL skip(같은 slug running 건너뜀) 절은 유지.

- **tier**: user=0 > reprobe=1 > batch=2.
- **값 도출**: `enqueue_job` 안에서 `2 if via=='batch' else (1 if kind=='reprobe' else 0)` 으로 *계산해 박는다*. 호출자(`bot/main.py`·`register_batch.py`)는 priority 를 안 넘김 — via/kind 만 넘기던 그대로. → via 가 입력 SoT, priority 는 그 materialized 출력 (둘이 모순날 경로 없음).
- **claim 순서만** 바꾼다. running 잡 preempt 안 함 — `register.py` subprocess + `chromium_lock` 은 못 죽인다(`bot/worker.py:stop()` 명시). 사용자 worst-case = in-flight batch 잡 1개 끝날 때까지(pool_size=2 라 둘 다 batch 면 ≤1 잡 분량 대기).
- **strict** — aging 없음. 사용자 enqueue 는 rate-limit(`count_user_register_jobs_since`)으로 bounded 라 batch starvation 은 실질 불가.
- **`queue_position` 동반 수정**: `COUNT(pending WHERE priority < me OR (priority = me AND id ≤ me))`. 안 하면 ack "N번째" 가 FIFO 기준으로 계산돼 거짓말(뒤로 정렬되는 batch 를 앞에 셈).
- **마이그**: `ADD COLUMN priority NOT NULL DEFAULT 0` + 1회 `UPDATE jobs SET priority = CASE WHEN via='batch' THEN 2 WHEN kind='reprobe' THEN 1 ELSE 0 END` backfill. `_migrate` 의 attempts 컬럼 추가 패턴(duplicate-column swallow) 그대로.

## Why

claim 순서만 손대는 게 최소 변경이면서 실제 통증(사용자가 batch backlog 뒤에 묶임)을 정확히 없앤다. preempt 는 코드상 불가하고(subprocess kill 못 함) pool_size=2 + 짧은 잡이라 굳이 worker 슬롯 예약 같은 복잡도도 불필요 — worst-case 가 이미 "in-flight 1개" 로 충분히 작다.

## Considered Options

- **derive-at-read (컬럼 X), `claim_next_pending` 의 `ORDER BY` 에 `CASE via/kind` 직접** — ADR 0002(fail_kind 파생) 정신과 일치, 마이그 0. **기각**: 사용자가 명시 컬럼 선호 — indexing/감사/미래 boost 여지. 단 ADR 0002 와 달리 stored 를 택했으므로 *값을 enqueue 에서 via 로부터 도출*해 SoT 중복(via vs priority)을 봉합(컬럼은 materialized, 입력은 여전히 via 하나).
- **호출자가 priority 인자 직접 전달** — 미래 "이 잡만 boost" 유연. **기각**: 호출자마다 via·priority 수동 정합 책임 → 어긋남 위험. 필요해지면 그때 enqueue 에 override 인자 추가(현재 YAGNI).
- **batch aging (오래 대기 시 승급)** — starvation 완전 차단. **기각**: rate-limit 으로 starvation 실질 불가라 ORDER BY 에 created_at 계산 추가가 over-engineering.
- **worker 슬롯 1개를 user/reprobe 전용 예약** — batch 둘 다 점유 못 하게. **기각**: claim 로직 복잡 + batch throughput 절반. worst-case "in-flight 1개 대기" 가 이미 수용 가능.
- **reprobe 를 batch 아래(최하위)로** — 깨진 사이트 재-probe 는 다음 폴링 주기에 또 옴. **기각**: 기존 구독 서비스 복구가 무인 backfill 보다 가치 높음 → reprobe 를 batch 위, user 아래 중간.

## Amendment (2026-05-21) — batch 2단 분리 + 동시 처리 5

batch 단일 tier(2) 를 **2단**으로 쪼갬: 한 batch 의 untried bulk 를 돌리는 중에 *이전 batch 의 실패분을 재시도/테스트* 하면 그 retry 가 새 bulk backlog 뒤에 묶이는 통증이 ADR 0009 의 원래 문제(사용자가 batch 뒤에 묶임)와 같은 모양으로 batch 내부에서 재현됐다.

- **새 tier**: user=0 > reprobe=1 > **batch-retry=2** > **batch=3**. (기존 batch=2 → batch=3 으로 강등, 그 사이에 batch-retry=2 삽입.)
- **batch-retry 도출**: `register_batch.py` 가 retry 모드(`--failed`/`--rc`/`--force`) 또는 `--url` 명시 타깃이면 `via='batch-retry'`, 순수 catalog untried sweep 이면 `via='batch'`. via 가 여전히 입력 SoT — `_derive_priority` 가 batch-retry→2, batch→3 도출.
- **마이그 갱신**: backfill CASE 에 `WHEN via='batch' THEN 3 WHEN via='batch-retry' THEN 2 ...`. 컬럼 신규일 때만 1회 실행이라 기존 N100 DB(이미 backfill 됨)는 영향 없음 — 신규 enqueue 만 새 값. 옛 pending batch(=2) 는 큐 drain 되며 자연 소멸.
- **동시 처리 3→5**: N100 `config.local.toml` 의 `worker.pool_size`·`chromium_lock.slots` 둘 다 5 (git-untracked per-machine override). RAM 12Gi·available ~7.6Gi·swap 0 → chromium context 5개(~1–2Gi) 안전 마진. CPU(8코어 loadavg ~1.6) 는 제약 아님. preempt 불가 전제(running 잡 안 죽임)는 그대로 — worst-case 는 "in-flight 잡 끝날 때까지" 인데 pool 5 라 retry 가 새 bulk 보다 먼저 *claim* 되므로 backlog 깊이와 무관히 다음 빈 슬롯을 가져감.
