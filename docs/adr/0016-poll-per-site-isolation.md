# ADR 0016 — 폴링 사이트별 isolation (wall timeout + progressive upsert)

작성: 2026-05-25  
상태: accepted (2026-05-25 사용자 승인, codex 검토 6건 반영)  
관련: ADR 0006 (폴링↔발송 분리), ADR 0015 (worktree)

## 1. Context

`scripts/poll.py` 가 `asyncio.gather(*tasks)` 1개로 1660 사이트 묶고 posts 캐시(sqlite)는 gather 끝난 뒤에 일괄 박는 구조였다. 2026-05-25 08:20 폴링이 어느 ad-heavy 사이트(politico/techpowerup/sitepoint 등 추정) chromium fetch 에서 30분+ hang → gather 가 끝나지 않아 1031개 사이트의 새 글이 posts 테이블에 안 박힘 → 08:30 발송창은 어제 잔여 LLM 필터만 돌리고 0건 발송 → 사용자에게 "📭 새 공지 없음".

마지막 정상 폴링 = 2026-05-24 08:28 (6분 52초 완료).

### Root cause

(a) `asyncio.gather` 가 끝나기를 기다린 *뒤에* posts 캐시를 박는다 → 1개 hang = 1000개 lost  
(b) 사이트별 wall timeout 없음 — `playwright_html._goto` 안의 nav/idle/quiet cap 은 있으나 chromium driver pipe 끊김·`page.content()` 등 외곽에서 hang 가능  
(c) systemd 단에 `RuntimeMaxSec` 없음 — 외곽 안전망도 없음  
(d) 어느 사이트가 hang 했는지 surface 없음 (start/done 로그 0)

### Industry parallels

- **Prometheus blackbox_exporter**: target 별 `scrape_timeout` (default 120s). 1 target fail = 다른 target 영향 X. `probe_duration_seconds` metric 으로 hung 즉시 식별.
- **Scrapy**: `DOWNLOAD_TIMEOUT` per-request, `CONCURRENT_REQUESTS_PER_DOMAIN`, memory soft limit.
- **asyncio.wait_for** (3.11+ `asyncio.timeout`): per-task wall cap, CancelledError 정상 전파.

`asyncio.TaskGroup` 은 우리 목적 (1 fail 해도 999 살리기) 과 반대 (batch fail-fast) — 채택 X.

## 2. Decision

폴링에 4-layer isolation 박음:

### P1. per-site asyncio.wait_for (180s)

`scripts/poll.py` 에 `_site_with_timeout(st, *, timeout, **kw)` 래퍼 추가. 호출은 `asyncio.create_task(_site_with_timeout(st, timeout=180s, …))`. 1 사이트만 `asyncio.TimeoutError` → 그 사이트의 `last_status="poll_timeout"` + `consecutive_breakage++`, 다른 사이트 그대로 진행.

`task_exception` 과 *별도* status 라 dashboard 가 둘 구분 가능 (codex 권고).

CLI: `--site-timeout SECS` 로 override 가능.

### P2. progressive posts upsert (gather 안 기다림) + 순서 정의

`_process_site` 안에서 sqlite `posts` 테이블에 INSERT OR IGNORE 직접 박음. 기존 line 530 의 batch upsert 제거.

**ordering** (crash safe):
1. `run_dir/<slug>.new.json` 쓰기 (collected 아티팩트)
2. `db_conn.execute(...)` × N + `commit()` (사이트당 1 batch commit, codex 권고)
3. `seen_post_ids = _new_seen` (in-memory)
4. `state.json` 디스크 flush

②/③ 사이 crash → 다음 폴링이 같은 글 재발견 → INSERT OR IGNORE idempotent. ③/④ 사이 crash → state.json 에 seen 미반영 → 다음 폴링이 다시 박음 (idempotent). **state.json 의 seen 은 sqlite 박힌 글만 인정** 이 invariant.

동시성: single `sqlite3.Connection` + `asyncio.Lock`. WAL 모드 (`bot/db.connect()`) 라 read 동시 OK, writer 1 직렬은 sqlite 자체 제약. 1660 사이트 × 평균 5글 ≈ 8k write 부하 ≪ 네트워크 — aiosqlite/ThreadPoolExecutor 까지 안 감.

### P3. observability — stderr fetch 진입/탈출 + duration_ms

`_site_with_timeout` 가 stderr 로 `[poll] start <slug>` / `[poll] done <slug> t=Xms` / `[poll] TIMEOUT <slug> t=Xms cap=180s` / `[poll] ERROR <slug> t=Xms <ExcType>` 1줄. systemd journal 이 받음.

성공 시 `state.last_poll_duration_ms = X` 박음. dashboard 가 p99 outlier 식별 가능 (별도 차후 surface).

### P4. systemd outer safety net

`deploy/notice-poll.service` 에:
```
RuntimeMaxSec=1200
KillMode=mixed
TimeoutStopSec=30
```

P1 의 코드 timeout 우선 작동, 그게 미작동(signal handler 무한 hang, GIL 데드락 등)이면 systemd 20분 후 SIGTERM→SIGKILL. 정상 폴링 ≈ 7분의 3× 여유.

### P+. playwright_html.close_session cleanup 캡 (codex 권고 1)

`engine/strategies/playwright_html.py:close_session` 의 4단계 close (`_page/_context/_browser/_pw`) 각각 `asyncio.wait_for(..., timeout=5.0)` + `BaseException` catch. wait_for cancel 도중에도 best-effort 로 4 핸들 다 None 처리. open_session mid-hang 으로 `__aenter__` 미완료 케이스는 P1 wait_for 가 `_process_site` 전체를 죽이므로 ConfigAdapter `__aexit__` 안 불려도 OK — chromium 프로세스 leak 우려는 P4 의 `KillMode=mixed` 가 외곽에서 정리.

### P++. 폴링 주기 = daily 08:20 (사용자 결정, drift 해소)

repo `deploy/notice-poll.timer` 가 `*-*-* *:20:00` (hourly) 였으나 N100 은 `*-*-* 08:20:00` (daily) 로 drift 됨 (2026-05-11 이전 변경, docs/배포 가이드.md §politeness 에 기록). 2026-05-25 사용자 확인 — **daily 가 정답**. 정중함(robots/rate-limit) + N100 부하 이유. ADR 0006 의 "시간당 폴링" 표현은 이 ADR 로 superseded. repo timer → daily 로 sync.

08:30 기본 발송창 직전 10분에 fresh 데이터 공급 — daily 1회로 충분.

## 3. Consequences

긍정:
- 1 사이트 hang 이 1000 사이트 영향 X (incident 모드 봉합)
- 어느 사이트가 hang 했는지 journal 한 줄로 surface — 다음 사고 진단 5분 안 끝남
- sqlite upsert 가 사이트별 progressive — gather 끝나기 기다릴 일 X
- systemd 가 외곽 안전망 — P1 미작동 시에도 폴링 unit 이 영원히 살아있지 X

부정·위험:
- sqlite Lock 으로 write serialize — 8k write 직렬은 부하 작지만 측정 必 (다음 폴링 후 p99 봄)
- chromium 단일 사이트 timeout 시 다음 chromium 사이트 launch 비용 — sem_chromium=1 이라 그대로
- `RuntimeMaxSec=1200` 이 너무 짧으면 정상 폴링도 죽음 — active 사이트 늘어 7분 → 15분 가면 cap 도 올림. journal `RuntimeMaxSec exceeded` 로 surface

비-결정 (다음 ADR 후보):
- playwright daemon (`notice-pw-daemon.service`) 활용 (RAM/launch 비용) — 이번 사고 직접 무관
- worker pool 패턴 (bot worker 같은 잡 큐) — P1-P4 로 isolation 달성됨, scope 외
- 사이트별 timeout config (engine schema 의 `timeout` 키와 wall timeout 통합) — v1 = 글로벌 상수만

## 4. 영구 게이트 (CLAUDE.md §8a)

이 ADR + `scripts/poll.py` 의 `POLL_SITE_TIMEOUT_S` 상수와 `_site_with_timeout` 래퍼가 영구 게이트. 동시에:

- `scripts/poll.py` docstring 에 architecture 1-2줄 + ADR 0016 ref
- `deploy/notice-poll.service` 의 주석에 ADR 0016 ref
- `engine/strategies/playwright_html.py:close_session` 의 주석에 *각 close 5s cap* 이유

다음 future Claude/codex 가 `gather` + post-gather write 패턴을 만들지 않게 reference.

## 5. 검증

- pre-push hook `probe_smoke --stage 3 --stage 5` (필수)
- dev 박스 손-poll 1회 (active subset) — `journalctl` 에 `[poll] start <slug>` 줄 가시화 확인
- N100 배포 후 다음 polling cycle (08:20) 에 어떤 사이트가 timeout 나는지 journal 확인 — 이번 incident 의 hung site 식별

## 6. 향후

- p99 outlier 식별 → 그 사이트 config 진단 (수동, 다음 세션)
- 1주 운영 후 cap 조정 여부 결정 (180s ↑ / ↓)
- `state.last_poll_duration_ms` dashboard surface
