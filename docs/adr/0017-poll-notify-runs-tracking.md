# ADR 0017 — poll/notify runs 추적 + 영속화 검증

작성: 2026-05-25
상태: accepted (codex 1차 리뷰 반영 — CRITICAL 2건, HIGH 4건, MED 5건, LOW 4건 적용)
관련: ADR 0016 (per-site isolation), ADR 0006 (per-user delivery), ADR 0018 (cron×commit race), 2026-05-25 incident doc

## 1. Context

2026-05-25 incident:

1. cron 폴링이 hang → 일부 사이트 새 글 `posts` sqlite 에 안 박힘 (ordering 버그).
2. 봇이 다음 발송창에 "📭 새 공지 없음" 보냄.
3. **사용자가 신고하기 전까지 운영자는 사고를 몰랐다** — 추적 데이터가 없음.

ADR 0016 이 *per-site wall timeout + progressive upsert* 로 1차 isolation 박았다. 그러나:

- 폴링이 *시작했는지·끝났는지* 도 영속 데이터에 안 남음.
- `collected/*.new.json` row 들이 *진짜로* `posts` sqlite 에 박혔는지 검증 안 함.
- 발송창 `deliver_due` 도 같은 사각지대.
- 대시보드는 *현재 시점* state.json 만 봄. "이번 cron run 에서 어느 사이트가 timeout 했나" 같은 질문 응답 X.

### Industry parallels

- **Prometheus**: 모든 scrape 가 `up{job, instance}` 메트릭 1 sample. 0 이면 alert.
- **Cron heartbeat (cronitor / healthchecks)**: job start ping + end ping → 안 오면 alert.
- **Airflow**: DAG run = 1 row + per-task TaskInstance row. State + duration 영속.
- **Celery flower**: per-worker · per-task in-flight/done 라이브 뷰.

우리 환경 = 단일 N100, 1660 사이트, sqlite 단일 DB. Airflow 같은 full 스택 over-engineering — 핵심: *영속 row + dashboard surface*.

## 2. Decision

bot.sqlite3 에 4 테이블 추가 + `scripts/poll.py`·`scripts/deliver_due.py` 가 row 박음. dashboard `/runs` 라우트 (FastAPI/Jinja, 기존 `dashboard/app.py`).

### 2a. 스키마

```sql
-- 폴링 1 회 = 1 row. process 시작 직후 INSERT, 끝/crash 시 UPDATE.
-- 영구 join key = id (INTEGER PK). run_label = 사람용 timestamp+pid (collision-safe).
CREATE TABLE poll_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_label   TEXT NOT NULL,                 -- 20260525_082057_pid12345 (collected dir basename + pid)
    started_at  TEXT NOT NULL,
    ended_at    TEXT,                          -- status='running' 일 때만 NULL (invariant)
    reaped_at   TEXT,                          -- reaper 가 crashed/killed 박은 시각
    reap_reason TEXT,                          -- 'stale_timeout' / 'liveness_dead'
    pid         INTEGER NOT NULL,
    host        TEXT,                          -- socket.gethostname() — N100 vs dev 구분 + reaper liveness 키
    git_sha     TEXT,                          -- ADR 0018 — HEAD at start
    args_json   TEXT,                          -- sys.argv[1:] JSON
    n_sites     INTEGER,                       -- 폴링 대상 (lurking 제외 후)
    n_done      INTEGER DEFAULT 0,
    n_timeout   INTEGER DEFAULT 0,
    n_error     INTEGER DEFAULT 0,
    n_lurking_skipped INTEGER DEFAULT 0,       -- lurking-skip 으로 처음부터 제외
    n_attempted_unique INTEGER DEFAULT 0,      -- 발견한 새 글 unique 합계
    n_inserted        INTEGER DEFAULT 0,       -- INSERT 직후 rowcount 합계 (실 추가)
    n_present_after   INTEGER DEFAULT 0,       -- INSERT 후 SELECT COUNT 합계 (검증)
    persist_mismatch_sites INTEGER DEFAULT 0,  -- n_present_after != n_attempted_unique 인 사이트 수
    duration_ms INTEGER,
    status      TEXT NOT NULL DEFAULT 'running' CHECK (status IN
                ('running','done','crashed','killed'))
);
CREATE INDEX idx_poll_runs_started ON poll_runs(started_at DESC);

-- 사이트 1 회 폴링 = 1 row. start 시점에는 INSERT 안 함 — finish 시 한 번만 INSERT
-- (codex HIGH: 1660 사이트 × INSERT+UPDATE = transaction budget 폭증). 사이트 살아있는 중
-- in-flight 표시는 poll_runs 의 합계 + collected/*.new.json 존재로 dashboard 가 추론.
CREATE TABLE poll_site_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES poll_runs(id),
    slug        TEXT NOT NULL,
    started_at  TEXT NOT NULL,                 -- finish 시 같이 박음
    ended_at    TEXT,                          -- reaper 가 child reap 시 채움
    status      TEXT NOT NULL CHECK (status IN
                ('ok','lurking','breakage','poll_timeout','task_exception',
                 'persist_mismatch','body_empty_drift','reprobe_enqueued',
                 'reprobe_skipped_bug','reprobe_enqueue_failed','run_crashed','error')),
                 -- 'error' = config 파일 없음/로드 실패 (_fetch_one 의 res['status']='error').
    n_posts            INTEGER DEFAULT 0,
    n_new              INTEGER DEFAULT 0,
    n_attempted_unique INTEGER DEFAULT 0,
    n_inserted         INTEGER DEFAULT 0,
    n_present_after    INTEGER DEFAULT 0,
    duration_ms INTEGER,
    error_msg   TEXT,
    note        TEXT,                          -- missing post_ids JSON, dup count, 기타
    UNIQUE(run_id, slug)
);
CREATE INDEX idx_poll_site_runs_run ON poll_site_runs(run_id, slug);
CREATE INDEX idx_poll_site_runs_slug ON poll_site_runs(slug, started_at DESC);

-- deliver_due 1 회 = 1 row.
CREATE TABLE notify_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    reaped_at   TEXT,
    reap_reason TEXT,
    pid         INTEGER NOT NULL,
    host        TEXT,
    args_json   TEXT,
    now_hhmm    TEXT,
    today_kst   TEXT,
    n_due_targets    INTEGER DEFAULT 0,
    n_targets_ok     INTEGER DEFAULT 0,
    n_targets_failed INTEGER DEFAULT 0,
    n_posts_delivered INTEGER DEFAULT 0,
    n_empty_notices  INTEGER DEFAULT 0,
    duration_ms INTEGER,
    status      TEXT NOT NULL DEFAULT 'running' CHECK (status IN
                ('running','done','crashed','killed'))
);
CREATE INDEX idx_notify_runs_started ON notify_runs(started_at DESC);

-- target 1 회 flush = 1 row. finish 시 INSERT (같은 이유).
CREATE TABLE notify_target_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES notify_runs(id),
    target_kind TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    status      TEXT NOT NULL CHECK (status IN
                ('ok','empty','no_subs','failed','exception','run_crashed','skipped_test_target')),
                 -- 'skipped_test_target' = NOTIFY_TEST_TARGETS allow-list 밖 dry-run skip (codex MED).
    n_posts     INTEGER DEFAULT 0,
    n_chunks    INTEGER DEFAULT 0,
    duration_ms INTEGER,
    error_msg   TEXT,
    UNIQUE(run_id, target_kind, target_id)
);
CREATE INDEX idx_notify_target_runs_run ON notify_target_runs(run_id);
CREATE INDEX idx_notify_target_runs_target ON notify_target_runs(target_kind, target_id, started_at DESC);
```

**LOW (codex)**: `run_label` 에 pid suffix 로 collision 회피. join key 는 INTEGER id. `ended_at IS NULL` invariant = `status='running'` (reaper 가 reaped_at·duration_ms·status 한 번에 채움).

### 2b. poll.py 변경 — start/finish + persist verification

1. `_run_inner` 진입 시 `poll_run_start(conn, run_label, pid, host, git_sha, args_json, n_sites)` → INSERT row, status='running', `started_at`. 같은 connection.
2. 같은 함수가 먼저 `_reap_stale_poll_runs(conn)` 호출 — reaper §2e 의 룰로 옛 running row 마킹 + 그 children 도 `run_crashed`.
3. **per-site start 시점에 INSERT 안 함** (codex HIGH — transaction budget). `_process_site` 끝/timeout/exception 직전에 `poll_site_run_finish(conn, run_id, slug, started_at, status, counts, error_msg, note)` 가 **한 번에 INSERT**. crash 로 finish 못 부른 사이트는 reaper §2e 가 `poll_runs.n_sites - count(poll_site_runs.run_id=run_id)` 만큼 `run_crashed` row 박음 (별도 reap pass).
4. **5d 영속화 검증** (CRITICAL — codex 수정):
   - `_process_site` 안에서 새 글 `new_posts` 가 있으면:
     - `n_attempted_unique = len({post_id for post in new_posts})`
     - sqlite upsert: INSERT OR IGNORE × N, `commit()`, **그리고 `cur.rowcount` 합계 = `n_inserted`** (실 추가 = 처음 본 글).
     - 검증: `SELECT post_id FROM posts WHERE slug=? AND post_id IN (...)` → `n_present_after = len(result)`.
     - `n_preexisting = n_present_after - n_inserted`.
     - **mismatch 조건**: `n_present_after != n_attempted_unique` → `status='persist_mismatch'`, `note=f"missing_ids={sorted(attempted-present)[:20]}"`.
   - **CRITICAL 회복 invariant**: mismatch 발생 시 *missing* id 는 `seen_post_ids` 에 박지 X. `_new_seen` 후보에서 missing 만 제거 후 박음. collected `.new.json` 은 그대로 유지 (다음 폴링·backfill 의 회수 자료). `_save_state` ordering 그대로 (ADR 0016 §2 P2).
5. `_run_inner` 끝 `poll_run_finish(conn, run_id, aggregates, duration_ms)` → status='done', n_* 합계.

### 2c. deliver_due.py 변경

1. `main` 시작 `notify_run_start(conn, pid, host, args_json, now_hhmm, today_kst)`.
2. 각 `flush_target` 시작 — INSERT 없음 (poll.py 와 같은 이유, transaction budget). finish 만.
3. `flush_target` 끝/실패 시 `notify_target_run_finish(conn, run_id, target_kind, target_id, started_at, status, counts, error_msg)`.
4. `main` 끝 `notify_run_finish(conn, run_id, aggregates, duration_ms)`.

### 2d. dashboard `/runs` 페이지 (FastAPI/Jinja)

`dashboard/app.py` 에 라우트 + `PAGE_SOURCES` 에 `("/runs", ("bot_db",))` 추가:

- `GET /runs?kind=poll|notify&status=&slug=&limit=100` — 최근 runs 표. kind 미지정 = 둘 다, timeline 통합.
- `GET /runs/poll/{id}` — 그 run 의 per-site breakdown (status, duration, persist counters, error_msg, note). slug query filter 지원.
- `GET /runs/notify/{id}` — 그 run 의 per-target breakdown.
- 컬러: running=노랑, done=초록, crashed/timeout/persist_mismatch=빨강, lurking/empty=회색.
- "현재 in-flight" 카드 — `poll_runs.status='running'` rows + 경과 시간.
- `poll_runs.git_sha` 가 직전 run 과 다르면 색 표시 (ADR 0018 의 cron×commit race 가시화).
- 사이드바 active state + PAGE_SOURCES 에 등록.

### 2e. reaper 룰 (codex HIGH/MED 통합)

`_reap_stale_*` 호출 시점 = `poll_run_start` / `notify_run_start` 직전. 같은 connection.

- **poll_runs reaper**: `status='running' AND started_at < now - 2h` 인 row 마킹.
  - 같은 `host` 면 `pid` liveness 확인 — `os.kill(pid, 0)` 시도 (Linux/N100), Windows 는 host 비교 후 skip (dev 박스는 단일 행). pid alive → reap **skip** (`reap_reason='liveness_alive_skip'` 안 박음, row 유지). dead → `reap_reason='liveness_dead'`.
  - 다른 host → 단순 timeout reap (`reap_reason='stale_timeout'`).
  - 2h 임계는 ADR 0016 의 `TimeoutStartSec=1200`(20분) × ~6 — 정상 폴링 7-15분, anti-bot 30분 도 안 넘는다는 사용자 손-`--all` 실측 후 확정. 임계는 `_POLL_REAP_THRESHOLD_S` 상수.
- **child reaper** (CRITICAL — codex HIGH): poll_runs row 가 crashed/killed 박힐 때, *없는 child* (= `poll_runs.n_sites` 보다 적은 `poll_site_runs` row 수) 만큼은 우리가 모름 → 그 차이를 *집계 row* 1건으로 박음: `poll_site_runs(run_id, slug='_unknown_', status='run_crashed', error_msg='reaper: parent crashed, site finish not recorded', note=f"missing_count={delta}")`. 개별 slug 알 길 없음 — 차후 dashboard 에 "이 run 의 {delta} 사이트 finish 미기록" 안내.
- **notify_runs reaper**: 같은 패턴. 임계 = `_NOTIFY_REAP_THRESHOLD_S` = 15min (정상 deliver 1-3분 + LLM·Discord backoff 여유). worst-case 측정 후 조정.

### 2f. 추적 helper 의 best-effort 의미 (codex HIGH)

모든 tracking helper (`poll_run_start/finish`, `poll_site_run_finish`, `notify_*`, `_reap_*`) = best-effort. 정의:

- `try/except sqlite3.OperationalError` 으로 감쌈. fail 시 그 호출의 transaction 만 rollback (`conn.rollback()`), 다른 transaction (예: posts INSERT) 에 영향 X.
- fail 시 stderr `[tracking] ⚠ <fn> failed: <err>` 1줄. counter 안 박음 (자체 fail 추적도 over-engineering).
- 호출 측은 *반환값을 보지 않음* (poll_run_start 가 None 반환 가능 → run_id 못 박힘 → poll_site_run_finish 가 run_id=None 으로 호출되면 그쪽도 skip).
- *어떤 tracking fail 도 폴링 / 발송 본 흐름을 죽이지 않음*. 사이트 isolation = ADR 0016 그대로.

### 2g. silent fail surface (5d 후속)

`poll_run_finish` 가 `persist_mismatch_sites > 0` 인 경우 stderr `[poll] ⚠ persist_mismatch <N> sites — sqlite 에 안 박힌 새 글 있음 (run_id=<id>)` 1줄. **acceptance criterion 좁힘** (codex MED): dashboard 시각화 + stderr 만 — 봇 owner DM 푸시·이메일 알림 *없음*. owner 가 운영 dashboard 보러 오는 모델. proactive 알림은 별도 ADR.

### 2h. transaction budget (codex HIGH — accepted cost)

ADR 0016 가 사이트당 1 commit (posts upsert). 이 ADR 의 추가:

- per-site finish: +1 INSERT (1 commit) per site. 1660 사이트 = +1660 commit/run = +~100% 누적.
- per-poll start/finish: +2 commit/run (사실상 무시).
- reaper: +1~수개 commit/run.

총 추가 commit = ~1660/run. ADR 0016 의 8k posts INSERT 와 같이 `db_lock` 안에서 직렬화. WAL 모드 sqlite 의 disk write throughput (NVMe ≈ 1000+ commit/s) 충분 — 누적 1.5s 추가 예상. **검증 항목** (§5): 1660 사이트 `--all` 폴링 wall clock 측정해 acceptance.

site finish 의 INSERT 를 *모아서* 1 batch 커밋하는 최적화 옵션: `_finish_buffer` 에 N=50 row 모은 뒤 `db_lock` 안에서 1 commit. 1660/50 = 33 commit. 다만 *최신 row 가 commit 전 crash 시 lost* — 그건 reaper §2e 가 채워줌. **v1 = simple per-site commit. 측정 후 batch 도입 여부 결정**.

## 3. Consequences

### 긍정

- 폴링 죽음 = `poll_runs.status='crashed'` 대시보드에 빨간 row. 사용자 신고 전 잡힘.
- `persist_mismatch_sites > 0` = 5d silent fail 자동 감지. ordering 버그 종류 못 숨김.
- per-site duration · status 영속 → 패턴 분석.
- `git_sha` 영속 → cron×commit race (ADR 0018) 사후 분석 1분.
- isolation = ADR 0016 그대로. tracking 은 그 위에 *얹는* 영구 기록.

### 부정·위험

- sqlite write +1660 commit/run — measured cost (§5).
- 4 새 테이블 = bot.sqlite3 누적. TTL GC = `poll_site_runs.started_at < now-30d` (별도 `prune_runs` helper). poll_runs/notify_runs 는 90d.
- dashboard 라우트 + Jinja 템플릿 ~200 line 추가.
- 봇 worker `jobs` 와 무관 (jobs = register/reprobe, runs = poll/notify 추적). 이름 헷갈리지 않게 `_runs` suffix.

### 비-결정 (다음 ADR 후보)

- **owner DM 알림** — `persist_mismatch` / `status=crashed` 시 봇이 owner DM. 별도.
- **per-site timeout config** — engine schema 의 `timeout` 키와 `POLL_SITE_TIMEOUT_S` 통합. scope 외.
- **generic run tracking framework** (worker daemon, retry/idempotence 등) — 이번 ADR 의 영구 게이트 *밖*. codex LOW 권고대로 scope creep 방지.

## 4. 영구 게이트 (CLAUDE.md §8a)

이 ADR + `bot/db.py` 의 `_RUNS_SCHEMA` + `poll_run_*` / `notify_*` helper + `scripts/poll.py`·`scripts/deliver_due.py` 의 호출이 영구 게이트. 게이트 범위 = **poll/notify runs 추적만**. 새 background job 추적은 별도 ADR (scope creep 방지 — codex LOW).

동시에 적용:

- `scripts/poll.py` docstring 에 ADR 0017 ref + tracking 흐름.
- `scripts/deliver_due.py` 같은 ref.
- `bot/db.py` `_RUNS_SCHEMA` 위 주석에 ADR 0017 ref.
- `dashboard/app.py` PAGE_SOURCES 에 `/runs` 등록.
- `docs/대시보드 가이드.md` `/runs` 설명 추가.

## 5. 검증

- pre-push hook `probe_smoke --stage 3 --stage 5` (필수).
- dev 박스 손-poll 1회 (`--sites <slug>`) — `poll_runs` + `poll_site_runs` 행 박힘 + persist counters.
- **partial persist test** (codex MED) — `posts` 에 1건 미리 박은 채 폴링 → `n_inserted=N-1`, `n_present_after=N`, `n_preexisting=1`. status='ok'.
- **silent fail test** — sqlite UPSERT 직전에 monkeypatch 로 raise → `status='persist_mismatch'`, missing_ids note, seen 미진. 별도 `tests/test_runs_tracking.py`.
- dev 박스 손-deliver `--dry-run` — `notify_runs` + `notify_target_runs` 행 박힘.
- dashboard `/runs` 응답 200, 필터 query 동작.
- crash 시나리오 — `python scripts/poll.py` 중간 `Ctrl+C` → 다음 run 의 reaper 가 'crashed' 박는지 + child reaper 가 `_unknown_` row 박는지.
- **1660 사이트 `--all` wall clock 측정** (codex HIGH) — `_POLL_REAP_THRESHOLD_S` 임계와 transaction budget 둘 다 검증. 측정 결과 ADR 안 §5 에 기록.

## 6. 향후

- `/runs` 1주 운영 후 시계열 차트 (p95 duration_ms per slug) 추가 여부.
- `persist_mismatch` 빈도 누적 → root cause 패턴 → engine·strategy 진단 자동화.
- owner DM 알림 — 별도 ADR.
