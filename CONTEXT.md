# notice-watcher

공지사항 자동 알림 봇. 사용자가 URL 던지면 시스템이 사이트 구조 인식 (probe → recognizer → schema) 후 주기 폴링·Discord 알림. 자동 인식 실패 사이트는 사람-루프 (hand-config pipeline) 로 들어가 손-개입·자가개선 후 재배포.

## Language

**hand-config pipeline**:
*자동 등록 실패* 사이트 (.FAILED.json 마커) 가 들어왔을 때 진단 → probe 휴리스틱·prompt·schema·recognizer 개선 → cases 기록 → dev box push → N100 pull → 봇 재시작 까지 한 사이클. 사이트 구조 인식이 안 된 케이스 처리.
_Avoid_: probe 개선 루프 (probe 만이 아님), hand-config 워크플로 (실행 단위 강조 부족), 자가개선 사이클 (너무 추상), 자가개선 인프라 (인프라 자체와 혼동), bug-fix workflow (다른 카테고리 — 아래 참조).

**bug-fix workflow**:
*코드 버그* (.BUG.json 마커, rc=-1/-2/-3/-5/-99) 가 들어왔을 때 traceback 분석 → bot/scripts/engine 코드 자체 수정 → 테스트 → commit + push + N100 pull + 재시작 → `.BUG.json` clear. 사이트 구조 문제 아니라 시스템 측 결함. hand-config pipeline 과 별도.
_Avoid_: hand-config pipeline (등록 실패는 사이트 인식 못 한 케이스, 버그는 timeout/예외).

**interaction 응답**:
`/watch`·`/preview` 슬래시 명령 직후 Discord interaction token 으로 보낸 응답. ephemeral 가능, 토큰 ~15분 만료.

**ack 메시지**:
interaction 응답을 *채널 메시지로 promote* 한 것 (`jobs.ack_channel_id/ack_message_id` 저장). worker 가 phase + 결과 edit. token 만료 무관, 사용자가 슬래시 친 채널에 그대로 노출.
_Avoid_: "사용자 응답" (어느 채널인지 불명), "interaction 메시지" (promote 후엔 interaction 영역 벗어남).

**사용자 DM**:
봇이 사용자와 1:1 DM 채널에 따로 보내는 메시지. `/watch here=False` 일 때 폴링 결과 도착처. ack 와 무관한 별도 채널.

**OWNER DM**:
봇이 *owner (운영자)* 에게 보내는 1:1 DM. 일반 사용자 안 봄. 게이트 거부/에러/재시작 등 운영 알림 (`_dm_owner(...)`).
_Avoid_: "관리자 알림" (admin slash command 와 혼동).

**진입 시점**:
`/watch`·`/preview` 슬래시 핸들러 안, 잡 enqueue *전* 검사 시점. `is_rejected` / `is_registered` / `url_gate.check` / rate-limit / queue cap 다 여기. 통과해야 jobs row 생성.

**claim 시점**:
worker 가 큐에서 잡 꺼내 처리 시작할 때 (`_process_job_inner` 첫 단계). 진입 ~ claim 사이 race 흡수 위해 `is_rejected` / `is_registered` 다시 검사. subprocess 도 여기서 시작.

**subprocess (= register subprocess)**:
`scripts/register.py` 가 별도 OS 프로세스로 도는 무거운 작업 (~30초~수분). chromium 띄워 probe→recognize→generate→preflight→digest→baseline. 등록 시도 1회 = subprocess 1회. `blocking_register` 가 `subprocess.run(...)` 으로 호출.

**SQL skip (= claim-time slug skip)**:
`claim_next_pending` 의 SELECT 가 `slug NOT IN (SELECT slug FROM jobs WHERE status='running')` 으로 같은 slug 가 이미 running 인 pending 잡을 *건너뛴다*. job1 끝나야 job2 claim 가능. pool_size>1 에서 같은 slug 의 동시 subprocess 차단.

**slug-level 마커** (output/poll_state/&lt;slug&gt;.*.json):
- `.json` (no suffix) — 등록 성공 state (polling 대상)
- `.FAILED.json` — 자동 등록 실패 (LLM gen 실패 등), hand-config 풀리면 제거
- `.REJECTED.json` — 영구 거부 (board_shape rc=3 / policy rc=2 / admin reject)
- `.BUG.json` — timeout/예외 (rc=-1/-2/-3/-5/-99). operator 가 root cause 고친 후 또는 Claude Code 가 수정 + 푸는 마커

`is_rejected(slug)` = REJECTED+FAILED+BUG 셋 중 하나라도 있으면 True (subprocess 재시도 차단).

**fail_kind** (대시보드 `/jobs` 1차 분류, `result_rc` 단독으로 파생):
- `done` (rc=0) — 등록 성공
- `gen_fail` (rc=1, `.FAILED.json`) — LLM gen+검증 실패 → hand-config pipeline 대상
- `policy_reject` (rc=2, `.REJECTED.json`) — `_policy_check` 거부 (LOGIN_REQUIRED / BLOCKED_*)
- `gate_reject` (rc=3, `.REJECTED.json`) — recognizer / nav_only / meta_diverging / multi_host_hub / board_shape 게이트 거부
- `bug` (rc=-1/-2/-3/-99, `.BUG.json`) — 시스템 결함 → bug-fix workflow 대상

marker 보다 한 단계 더 세분화 — `.REJECTED.json` 한 마커가 `policy_reject`/`gate_reject` 둘로 갈림 (rc 로 구분).
_Avoid_: "fail_category" / "error_type" / "reject_kind" — 어휘 떠다님.

**fail_subkind** (대시보드 `/jobs` 2차 분류, `result_tail` regex 파생):
fail_kind 안의 sub. gen_fail → `[FAIL] <check>` 이름 (`posts_nonempty` / `article_body_len` / `published_at_iso` / `post_id_*` / `title_nonempty` / `gemini_api`); policy_reject → `login_required` / `blocked_bot/ip/geo`; gate_reject → `recognizer:<name>` / `nav_only` / `meta_diverging` / `multi_host_hub` / `board_shape`; bug → `chromium_lock_timeout` / `subprocess_timeout` / `subprocess_exception` / `worker_exception`.

`/jobs` 셀 2줄째에 작은 회색 글로 표시, hover 에 풀 reason text. DB 컬럼 X — `bot/fail_taxonomy.py:classify_fail()` 가 읽을 때 파생 (ADR 0002).

## Flagged ambiguities

- "probe 개선 루프" / "hand-config 워크플로" / "자가개선 사이클" 셋이 같은 개념 가리킴 — 결정: **hand-config pipeline** 으로 통일 (2026-05-17).
