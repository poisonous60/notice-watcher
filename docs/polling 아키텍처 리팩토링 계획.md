# polling 아키텍처 리팩토링 계획

상태: **승인됨 (2026-05-25 codex 검토 6건 반영 + 사용자 승인). 구현 단계.**
작성: 2026-05-25
계기: 2026-05-25 08:20 N100 폴링이 단일 사이트(미식별, ad-heavy 추정 = politico/techpowerup/sitepoint 등 중) chromium fetch 에서 30분+ hang → `asyncio.gather` 가 끝나지 않아 1031개 사이트 폴링 결과가 sqlite `posts` 테이블에 박히지 않음 → 발송창(08:30)이 어제 잔여 LLM 필터만 돌리고 0건 발송 → 사용자에게 "📭 새 공지 없음" 표시. 마지막 정상 폴링 = 2026-05-24 08:28.

## 0. TL;DR

지금 폴링은 1660 사이트를 **단일 `asyncio.gather()` batch** 로 묶고, posts 캐시는 batch **전체가 끝난 뒤** sqlite 에 쓴다. 사이트별 wall timeout 없음, systemd `RuntimeMaxSec` 없음. **1개 사이트만 hang 해도 다른 1000+ 사이트의 결과가 영원히 안 박힘**. 산업 표준은 이걸 (a) **per-task wall timeout** (b) **progressive write** (c) **multi-target exporter pattern** (d) **TaskGroup 또는 worker pool + queue** 로 푼다. 본 계획은 그 네 가지를 *소규모 점진* 적용 — 한 번에 전부 갈아엎지 X.

---

## 1. 현재 구조 정확 매핑

### 1a. poll.py 단일 batch

`scripts/poll.py:485-494`

```python
tasks = [asyncio.create_task(_process_site(st, …)) for st in states]
results = await asyncio.gather(*tasks, return_exceptions=True)
```

- 1660 사이트 (1031 active + 등록만/REJECTED/FAILED 잔여) 전부 한 batch.
- semaphore: `sem_chromium=1`, `sem_httpx=8` → 동시 fetch 상한.
- **per-task wall timeout 없음**. `_process_site` 내부 `fetch_list` 안의 network-level timeout(httpx/playwright)만 존재.
- chromium 은 사이트당 launch/close → 광고/anti-bot 챌린지 무한 대기 가능.

### 1b. posts 캐시 = gather 끝난 뒤 일괄 쓰기

`scripts/poll.py:530-546`

```python
posts_conn = bot_db.connect()
try:
    for f in run_dir.glob("*.new.json"):
        …
        for post in items:
            bot_db.upsert_post(posts_conn, slug, post)
```

→ gather 가 안 끝나면 0건 박힘. **이게 진짜 root**: 폴링 자체가 끝나도 1개 hang 만 있으면 999개 글이 lost.

### 1c. playwright_html fetch chain (개별 호출은 잘 묶임)

`engine/strategies/playwright_html.py:120-134`
- `page.goto(..., wait_until="domcontentloaded", timeout=nav_to=15s)` ✅ 캡
- `_wait_xhr_quiet(quiet_ms=500, hard_timeout_ms=2s)` ✅ 캡
- `page.wait_for_selector(..., timeout=2s)` ✅ 캡

이론상 _goto 최대 ≈ 19s. 그런데 30분+ hang 한다는 건 **chromium 자체 또는 playwright driver 의 pipe** 에서 응답이 안 오는 상태. `page.content()` 의 timeout 부재 또는 launch/close session 의 timeout 부재가 의심됨. **재현 어렵고, surface 도 안 됨** — fetch 진입/탈출 print 자체가 없음.

### 1d. httpx_html / httpx_json

`engine/strategies/httpx_html.py:23` `build_async_client(cfg)` — cfg.timeout 사용 여부 노출 X. 보수적으로 가정: httpx default = 5s. **단, 사이트가 chunked stream 으로 끊지 않으면 client 가 무한 read 할 수 있음**.

### 1e. systemd 가드

`deploy/notice-poll.service`
- `Type=oneshot`
- `RuntimeMaxSec` **없음** — systemd 가 process 를 죽일 시간 cap 없음. 30분+ hang 도 그대로 살아있음.
- `notice-poll.timer` = `OnCalendar=*-*-* *:20:00` (시간당 :20). **N100 에선 daily 08:20 으로 drift** (사용자/이전 세션이 N100 에서 직접 unit 편집한 흔적, CLAUDE.md §3 위반).

### 1f. notice-pw-daemon.service — 박혀있지만 미사용

systemd unit 은 N100 에 존재 (long-lived chromium daemon, `output/playwright_daemon/userdata_*`) 하지만 `engine/strategies/playwright_html.py` 에서 안 부른다. 즉 daemon 은 *준비된 자원*이고 매 폴링은 그걸 무시하고 fresh launch 한다. RAM 비효율 + chromium startup 비용 매번.

### 1g. 다른 폴링 가드: bot worker, deliver_due

- `bot/worker.py`: 잡 queue + per-slug `asyncio.Lock` + register subprocess 는 `DEFAULT_WALL_TIMEOUT_S=240` 으로 process-tree kill. → **이미 폴링 외 영역에는 wall-timeout pattern 적용돼 있음**. 폴링만 빠짐.
- `bot/delivery_tick.py`: 1분 tick 으로 deliver_due subprocess. `_running_proc` 중복 차단. subprocess 자체는 timeout 무 (LLM/Discord 각자 timeout 에 의존).

---

## 2. 산업 표준 (참고)

| 시스템 | 패턴 | 핵심 아이디어 |
|---|---|---|
| **Prometheus blackbox_exporter** | multi-target exporter | 각 target 별 `scrape_timeout` (기본 120s) 캡. exporter 가 timeout 초과 시 그 target 만 fail, 다른 target 영향 X. 타이밍 메트릭 (`probe_duration_seconds`) 으로 hung 즉시 surface. |
| **Scrapy** | per-request `download_timeout` + per-domain concurrency cap | 글로벌 `CONCURRENT_REQUESTS`, `CONCURRENT_REQUESTS_PER_DOMAIN`. 1개 사이트 slow → 그 domain 의 concurrency 자동 1 로 줄어듦. 메모리 soft limit 도달 시 신규 request 차단. |
| **asyncio.TaskGroup** (3.11+) | structured concurrency | exception 시 다른 task 자동 cancel. `gather` 보다 강한 안전성. 단 이건 *batch fail* 시 동작 — 우리는 정반대(1개 fail 해도 999개 살리고 싶음) 필요. |
| **asyncio.wait_for(coro, timeout)** | per-task wall cap | coro 자체에 timeout 캡슐. CancelledError 정상 전파. |
| **as_completed** | progressive | task 끝나는 대로 결과 yield. progressive write 자연스럽게 가능. |
| **Job queue + worker pool** (Celery/RQ/sidekiq) | 분산화 | job 등록 + N worker. worker hang = 다른 worker 영향 X. 우리 `bot/worker.py` 가 이미 같은 패턴 (register/reprobe 잡용). |

---

## 3. 제안 architecture

핵심 4 원칙:

**P1. per-site wall timeout (이미 register 에선 240s 박혀있음. 폴링도 같은 게이트)**
**P2. progressive posts upsert (사이트별로 끝나는 즉시 sqlite. gather 안 기다림)**
**P3. surface — 사이트 시작/끝 stderr 로그 + duration metric (state 파일에)**
**P4. systemd outer safety net — `RuntimeMaxSec=N00`**

### 3a. P1 — per-site wall timeout (+ cleanup 캡)

`_process_site` 호출 시 `asyncio.wait_for(_process_site(st, …), timeout=POLL_SITE_TIMEOUT_S)` 로 래핑. 기본 180s.

`TimeoutError` 발생 시 그 사이트만 `consecutive_breakage++` + `last_status="poll_timeout"` 박음 (기존 `task_exception` 와 *별도* status — codex 권고 6 반영. dashboard 가 두 상태 구분 가능).

**추가** (codex 권고 1): `engine/strategies/playwright_html.py:close_session` 의 4단계 close (`_page/_context/_browser/_pw`) 각각 `asyncio.wait_for(..., timeout=5s)` + `BaseException` catch 로 감싸 best-effort 진행. open_session mid-hang 대비 — `_process_site` 안에 explicit `try/finally` 로 `close_session` 호출. ConfigAdapter `__aexit__` 만 의존 X.

### 3b. P2 — progressive posts upsert (순서·batch commit 포함)

현 `_process_site` 마지막에서 (1) state 파일 쓰기 (2) `.new.json` 파일 쓰기 만 함. posts 캐시 (sqlite) upsert 는 line 530 gather 뒤에서 함.

**바꿈**: `_process_site` 안에서 `bot_db.upsert_post` 호출. `asyncio.Lock` + single sqlite connection (codex 권고 2 — aiosqlite/ThreadPoolExecutor 까지 안 가도 부하 ≪ 네트워크 시간).

**순서** (codex 권고 6): ① `.new.json` 쓰기 → ② sqlite upsert (사이트당 1 batch commit, codex 권고 3) → ③ seen_post_ids 갱신 → ④ state.json 쓰기. crash safe — sqlite 박힌 글만 seen 으로 인정.

### 3c. P3 — surface (fetch 진입/탈출 로그 + 메트릭)

`_process_site` 시작·끝에 `print(f"[poll] {slug}  start", flush=True, file=sys.stderr)` / `done t=Xs`. systemd journal 이 그대로 받음. 다음에 hang 나면 어느 slug 가 마지막 `start` 였는지 즉시 보임 — 이번 사고에서 가장 비싸게 잃은 정보.

추가로 `state.last_poll_duration_ms` 박음. dashboard 가 `/sites` 에서 sortable. p99 outlier 가 다음 hang 후보.

### 3d. P4 — systemd outer safety

`deploy/notice-poll.service` 에:
```
[Service]
…
RuntimeMaxSec=1200        # 20분 hard cap (어제 정상 6:52, 5× 여유)
KillMode=mixed            # 메인 SIGTERM, child SIGKILL
TimeoutStopSec=30
```

P1 의 코드 timeout 이 우선 작동, 어떤 이유로 그게 미작동(예: signal handler 무한 hang)이면 systemd 가 SIGKILL.

### 3e. (선택) playwright daemon 활용

`notice-pw-daemon.service` 는 long-lived chromium 으로 매 사이트 launch 비용 ~3s 절감 + RAM 안정. 단 이번 사고와 직접 관련 X (사고 = 단일 사이트 무한 hang). **이번 리팩토링 scope 에선 *제외*** — 별도 ADR 로 옮김. (요구 4 — "polling 을 순서대로 한다는 게 상식적이지 않은 구조" → 핵심은 isolation 이지 chromium 재사용 X. 일단 isolation 부터 박고 daemon 은 다음 round)

### 3f. (선택) TaskGroup 으로 마이그?

Python 3.11+ `asyncio.TaskGroup` 은 *batch fail-fast* 의미라 우리 목적과 반대 (1개 fail 해도 999개 살리기). `gather(return_exceptions=True)` + `wait_for` 가 더 맞음. TaskGroup 도입 안 함.

### 3g. (선택) prometheus-style job queue?

bot worker 같은 worker pool 패턴으로 폴링도 옮기는 큰 그림. 장점: hang 한 worker 만 SIGKILL, 다른 worker 살림. 단점: 큰 변경 + sqlite jobs 큐가 1660 사이트마다 row 만들기 비효율 (잡 수명 짧음). **이번 리팩토링 scope 외**. P1-P4 가 효과적으로 같은 isolation 을 *프로세스 내부* 에서 달성하므로 worker pool 까진 안 가도 됨. 추후 ADR 후보.

---

## 4. 변경 파일 목록 (예정)

```
scripts/poll.py
  - _process_site 호출을 asyncio.wait_for 로 래핑 (P1)
  - posts upsert 를 _process_site 내부로 이동, gather 뒤 batch 코드 제거 (P2)
  - print(slug start/done t=X) stderr (P3)
  - state.last_poll_duration_ms 박음 (P3)
  - timeout 상수 + CLI flag

engine/strategies/playwright_html.py
  - _goto 진입 시 stderr print(slug, url) (P3 보완 — fetch 위치까지 surface)
  - (별도 PR 후보) page.content() 에 explicit timeout

deploy/notice-poll.service
  - RuntimeMaxSec=1200, KillMode=mixed, TimeoutStopSec=30 (P4)
  - N100 unit 동기화 (drift 해소)
```

새 파일 없음. config schema 변경 없음 (선택적으로 site_timeout 키 추가 가능하나 v1 에선 글로벌 상수 만).

---

## 5. 마이그레이션 단계

1. **plan 확정 + codex review** (지금)
2. plan 사용자 승인
3. 작업 worktree 진입 (`bash scripts/session_start.sh poll-refactor`)
4. P1 + P3 먼저 (작은 변경, 즉시 hang surface 효과) — 1 commit
5. P2 — sqlite asyncio.Lock 도입, _process_site 내부 upsert. 기존 batch upsert 제거. — 1 commit
6. P4 — deploy/ unit 파일 수정. N100 drift 도 같이 sync (CLAUDE.md §3 위반 회수: dev box 에서 hourly 로 통일하고 N100 에 push) — 1 commit
7. dev 박스 local 폴링 1회 smoke (registered subset 으로) — pass 확인
8. push → N100 pull → `systemctl --user daemon-reload && restart notice-poll.timer`
9. 다음 :20 폴링 자동 트리거 확인. journal 에 `[poll] <slug> start` 로그 가시화 확인
10. 만약 다시 어떤 사이트 hang → P1 의 wait_for 가 그 사이트만 죽이고 나머지는 정상 진행 → posts 캐시 박힘 → 발송창 정상 → 사용자 알림 복구
11. p99 outlier site 식별 → 그 site config 수동 진단 (수동, 다음 세션)

---

## 6. 위험·롤백

- **sqlite write 직렬화 비용**: 1660 사이트 × 평균 N=5 글 upsert = ~8000 write. `asyncio.Lock` + single conn 으로 충분히 빠름(<10s 추정). aiosqlite 검토 가능.
- **wait_for cancel 시 chromium resource leak**: `_process_site` finally 에서 `close_session` 호출 보장 필요. CancelledError → finally 실행됨 (asyncio 보장). 단, finally 안에서 추가 await 가 또 cancel 되면 close 미완 → daemon 화 옵션 또는 close timeout 도 wait_for. 구현 시 주의.
- **RuntimeMaxSec 너무 짧으면**: 정상 폴링도 SIGKILL. 어제 정상 6:52, 정상 폴링이 5× 안에 끝난다는 가정. 만약 active 사이트 더 늘면 cap 도 올림. cap 발동 시 systemd journal 에 명시 → 알림.
- **N100 unit drift sync**: 누군가 N100 에서 daily 로 바꾼 의도가 있을 수 있음. 사용자 확인 필요 — *왜 N100 만 daily 로 바뀌었는지* memory 검색 + 사용자 직접 확인.
- **롤백**: `git revert` 1~3 commit. systemd unit 도 git 추적이라 revert + N100 pull + daemon-reload 로 회복.

---

## 7. 영구 게이트 (CLAUDE.md §8a)

이번 사고의 영구 게이트 = P1+P2+P3+P4 그 자체. 추가로 다음을 박음:

- `CLAUDE.md` 또는 `docs/운영 메모.md` 에 "폴링은 per-site wall timeout 必, posts 캐시는 progressive write" 룰
- ADR 신규: `docs/adr/0016-poll-per-site-isolation.md` — gather 통배치 폐기, per-site timeout, progressive write
- `scripts/poll.py` docstring 에 architecture 1-2줄

이 룰을 박는 이유는 다음 *오케스트레이션 실수*도 같이 잡기 위함 (`feedback-orchestration-mistakes-permanent-gate`): future Claude/codex 가 다른 곳에서 같은 패턴(batch gather + progressive write 누락)을 만들지 않게 reference.

---

## 8. 미해결 질문 (사용자 결정 필요)

1. **timeout 기본값**: 180s 적정? (현재 정상 사이트 fetch ≪ 30s, anti-bot 사이트 ≈ 17s nav cap. 5× 여유 = 90s 도 가능)
2. **posts upsert 직렬화 방식**: asyncio.Lock + single conn vs aiosqlite vs ThreadPoolExecutor sync sqlite. 첫 옵션이 가장 단순.
3. **N100 timer drift 해소 방향**: ✅ 2026-05-25 사용자 결정 — **daily 가 정답**. 정중함/N100 부하 이유로 의도적 변경됨. repo `deploy/notice-poll.timer` 의 `*-*-* *:20:00` (hourly) 표현 → `*-*-* 08:20:00` (daily) 로 sync. 같이 docs/배포 가이드.md, 운영 메모.md 의 "hourly" 어휘 → "daily" 정정.
4. **playwright daemon 활성화**: 이번 scope 에서 함 vs 별도 ADR. 후자 추천.
5. **state.last_poll_duration_ms** dashboard surface 시점: 이번 scope vs 다음.

---

## 9. codex 검토 요청 사항

이 plan 을 codex 에 넘길 때 묻는 점:
- isolation pattern (P1+P2) 가 chromium resource leak 없이 안전한지 (CancelledError → finally → close_session 체인)
- sqlite asyncio.Lock + single conn 이 1660 사이트 동시 upsert 부하에서 botleneck 아닌지
- TaskGroup/Worker pool 로 안 가도 P1-P4 면 충분한지 (over-engineering 아닌 충분 engineering)
- 다른 산업 패턴 (Twisted reactor, Trio supervisor 등) 우리 상황에 더 잘 맞는 게 있는지
- 변경 파일 3개 + 새 ADR 1개 가 *minimum viable refactor* 인지 (P1-P4 중 빠뜨려도 되는 게 있나)
