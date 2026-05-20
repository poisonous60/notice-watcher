# notice-watcher

공지사항 자동 알림 봇. 사용자가 URL 던지면 시스템이 사이트 구조 인식 (probe → recognizer → schema) 후 주기 폴링·Discord 알림. 자동 인식 실패 사이트는 사람-루프 (hand-config pipeline) 로 들어가 손-개입·자가개선 후 재배포.

## Language

**hand-config pipeline**:
*자동 등록 실패* 사이트 (.FAILED.json 마커) 가 들어왔을 때 진단 → probe 휴리스틱·prompt·schema·recognizer 개선 → cases 기록 → dev box push → N100 pull → 봇 재시작 까지 한 사이클. 사이트 구조 인식이 안 된 케이스 처리.
_Avoid_: probe 개선 루프 (probe 만이 아님), hand-config 워크플로 (실행 단위 강조 부족), 자가개선 사이클 (너무 추상), 자가개선 인프라 (인프라 자체와 혼동), bug-fix workflow (다른 카테고리 — 아래 참조).

**bug-fix workflow**:
*코드 버그* (.BUG.json 마커, rc=-1/-2/-3/-5/-99) 가 들어왔을 때 traceback 분석 → bot/scripts/engine 코드 자체 수정 → 테스트 → commit + push + N100 pull + 재시작 → `.BUG.json` clear. 사이트 구조 문제 아니라 시스템 측 결함. hand-config pipeline 과 별도.
_Avoid_: hand-config pipeline (등록 실패는 사이트 인식 못 한 케이스, 버그는 timeout/예외).

**즉답** (= hand answer — 사람이 답 박음, AUTO 추론 bypass):
register 의 추론(probe→gpt-5.4-mini)을 거치지 않고 *이미 아는 것* 에 사람이 미리 답을 박는 것. 두 형태 — 단일 config (URL 1개) · 플랫폼 config (URL 클래스). 추론을 *1도 안 똑똑하게 함* — 그래서 case `outcome: handcrafted`. scope(단일 vs 플랫폼)만 다르고 본질 같음.
_Avoid_: "일반화" (즉답은 미지 사이트 처리 능력 안 늘림 — 일반화 아님), "개선" (추론 안 변함).

**추론 개선** (= AUTO path 가 *미지* 사이트를 더 잘 풂):
register 의 generic 단계(probe 추출·LLM 생성·검증·게이트)를 똑똑하게 만들어 *앞으로 본 적 없는* 사이트도 자동 처리되게 하는 것. fix-layer C(probe 휴리스틱)·E(schema)·A(system prompt)·D(retry)·reject-gate recognizer·register 플로우·blacklist 학습. case `outcome: improved`. **improved 의 유일한 의미** — dashboard 에서 "파이프 진보" 카운트는 이것만 (즉답·거부는 toil/거부로 따로). [scope→mechanism re-cut: ADR 0005]
_Avoid_: "toil 줄임" 단독 (즉답도 toil 줄이지만 추론개선 X — 핵심은 *미지* 처리 능력).

**단일 config** (즉답의 한 형태, hand-config 스킬 §2e 산출):
gpt-5.4-mini 가 retry 후 못 만든 config 를 사람이 selector/path 채워 `configs/<slug>.json` 한 파일 손작성. canonical URL 1개만 커버. case `outcome: handcrafted`. 같은 패턴 다음 사이트 오면 또 손작성. **선택 기준**: 대상이 *단일 사이트* (플랫폼 판정 test = NO) 일 때. 플랫폼이면 플랫폼 config.
_Avoid_: "per-slug 손-config" (구 이름 — 길어서 폐기), "손-config" 단독 (스킬명 / `strategy:handwritten` 값과 떠다님), "일반화"/"개선" (즉답이라 둘 다 아님).

**플랫폼 config** (즉답의 한 형태, config 발급 recognizer):
`engine/recognizers/<plat>.py` 가 URL *클래스* 인식 → config 를 register 시 즉시 발급 (probe+LLM skip). 한 플랫폼 전체 커버, 다음 게시판 `/watch` 만으로 자동. **단일 config 의 parameterized 버전** — 1 URL 대신 URL 클래스에 답 박음. 추론 bypass 는 동일 → case `outcome: handcrafted` (improved 아님 — 추론 안 똑똑해짐, 그냥 dispatch table). 손-adapter 동반해도 (GoogleNewsRssAdapter) 즉답의 fetch 코드일 뿐. **선택 기준**: 대상이 *플랫폼* (판정 test = YES) 일 때. CLAUDE.md §8a 가 단일 config 보다 1순위로 미는 자리 (한 번에 플랫폼 전체).
_Avoid_: "recognizer 일반화" (구 이름 — 일반화/개선 아님, 즉답임), "플랫폼 hand-config" (hand-config 은 스킬명), "improved" (handcrafted 임 — ADR 0005).

**플랫폼** (= 재발 source 있는 URL 형태):
한 `host+path` 형태가 *서로 다른 여러 게시판/검색* 을 instance 로 내놓고, 그 instance 가 system 에 더 들어올 source 가 있는 것. **판정 test**: "이 URL 의 host+path 형태를 가진 *다른* 게시판이 앞으로 또 `/watch` 될 source 가 있나?" 재발 source 3종 — ① multi-tenant 호스트 (arca 채널 `/b/<ch>`·reddit `/r/<sub>`·네이버/다음 카페·tistory), ② parametric service (google search `?q=`), ③ 공유 CMS (여러 host 가 같은 SW — discourse·그누보드). → **플랫폼 config** 대상.
_Avoid_: "큰 사이트" (규모 무관 — 형태 재발이 기준), "게시판 여러 개" (한 사이트 고정 3판 ≠ 플랫폼 — instance source 가 아님).

**단일 사이트** (= 재발 source 없음):
URL 형태 재발 source 0. 한 기관의 고정 게시판 (예: ACM 윤리강령 페이지·대학 공지판). recognizer regex 가 딱 1개 URL 만 매칭 → 추상화 비용만, 일반성 0 (over-engineering). → **단일 config** 대상. case body 에 "재발 0 이유" 1줄 (CLAUDE.md §8a).
_Avoid_: "단일 게시판" (오해 source — arca 단일 채널도 게시판 1개지만 플랫폼 instance 라 플랫폼 config).

**recognizer** (`engine/recognizers/<plat>.py` 코드 아티팩트):
register 가 probe 전에 `recognize(url)` 호출 — URL 패턴 매칭 함수. **두 종류, 정반대 성격**:
- **config 발급 recognizer** (arca/google-news/naver-blog/tistory/discourse) → 플랫폼 config 즉답. `outcome: handcrafted`.
- **reject-gate recognizer** (`article_page_reject` 류) → 미지 사이트를 *올바르게 거부* = 분류 똑똑해짐. **추론 개선**. `outcome: improved`.

→ "recognizer 추가" 자체로는 outcome 안 정해짐 — *즉답 발급이냐 게이트냐* 가 정함.
_Avoid_: "recognizer = 일반화" (config 발급은 즉답 — F-layer 자리일 뿐 의미 bucket X).

**handwritten strategy**:
config 의 `strategy` 필드값. 손-adapter 클래스 경로 (`adapter:"<클래스>"` + kwargs) — LLM-gen schema 대신. **작성자 무관** — recognizer 가 자동 발급한 config 도 이 값 가짐 (arca/google-news). "손으로 썼다" 가 아니라 "손-adapter 경로 쓴다" 는 뜻.
_Avoid_: "손-config" (작성자 의미로 오독 — strategy 종류일 뿐).

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

**catalog**:
name+url 짝 모음 1개 단위. 파일 1개 = catalog 1개 (`output/candidates/<name>.yaml`, 파일명 stem = catalog 이름). git-ignored — 데이터 (URL list 자주 mutate). dev box 가 진본, `scripts/remote.py batch-register` 가 atomic scp 로 N100 동기 (CLAUDE.md §5 rule B 의 *shared operational input* 예외 — output/ 중 dev box 가 *쓰고* N100 이 *읽는* 유일한 자리). 분류 단위 X — 사용자가 한 번에 추가한 chunk 의 *git/편집 편의 partition*. 의미적으론 모든 catalog 합쳐서 1개 monotonic pool ("아직 안 해본 사이트들"). 이름은 가벼움 (날짜·번호 — 예: `2026-05-20.yaml`, `chunk-2.yaml`). dashboard "+ 새 catalog" 시 이름 비우면 `auto-YYYY-MM-DD-<seq>.yaml` 자동. 이름 규칙: `^[a-z0-9][a-z0-9_-]{0,63}$`. 같은 url cross-catalog dedup 강제 (driver load 시 검증, 겹치면 fail).
_Avoid_: "batch" (실행 단위 아님), "candidate list" (어휘 떠다님), "cohort" (분류 의도 X).

**catalog batch run**:
N100 의 `scripts/register_batch.py` 가 catalog 1개를 읽어 jobs 테이블에 `via='batch', ack_*=None` 으로 enqueue 하는 1회 실행. 사용자가 Discord 에서 `/preview URL` 매번 치는 걸 자동화 — bot worker 가 일반 path (claim 시점 가드 + subprocess) 그대로 처리. 결과는 `bot.sqlite3` 의 jobs 행 + slug-level 마커로 박힘. 기본 untried-only (jobs 에 같은 url row 없는 entry 만), `--force` 시 같은 slug 의 `.REJECTED/.FAILED/.BUG.json` 마커 자동 삭제 후 재enqueue. dev 박스 → `scripts/remote.py batch-register --catalog=<name>` (SSH wrapper) 또는 dashboard `/candidates` "▶ batch run" 버튼으로 호출.
_Avoid_: "batch register" (`/preview` 와 같은 단어라 헷갈림), "bulk preview" (정확하지만 어휘 떠다님), "catalog batch" (단위/동작/흐름 혼동 — 2026-05-20 split).

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

**LLM call_site**:
코드 안의 LLM 호출 지점 식별자 (`notify_summarize`, `notify_filter`, `config_generate`, `config_retry`, ...). `output/llm_routing.json` 이 call_site → `<provider>:<model>` 매핑. provider/model 바꿀 때 호출 코드 안 건드리게 하는 indirection. 새 호출 지점 추가 = 새 call_site 박고 routing.json 에 entry 추가.
_Avoid_: "Gemini 호출" / "LLM API 호출" (provider 박힌 어휘 — 실제 매핑은 routing.json 결정), "endpoint" (HTTP 어휘 — codex 는 subprocess).

**provider**:
LLM 백엔드 종류. 현재 박힌 것: `gemini` (HTTP API, multi-key rotation), `codex` (subprocess CLI, ChatGPT Plus OAuth 5h quota window), `openrouter` (HTTP API). `llm_routing.json` 의 `<provider>:<model>` 좌측 값. notify·generate 의 span name·로그·type hint 는 provider-neutral 로 유지 (`summarize_llm` / `LLMClient`) — 매핑만 바꿔도 코드 안 바뀜.
_Avoid_: "Gemini" 단독 (현재 notify path 는 codex), "백엔드" (모호 — DB 백엔드와 헷갈림).

## Flagged ambiguities

- "probe 개선 루프" / "hand-config 워크플로" / "자가개선 사이클" 셋이 같은 개념 가리킴 — 결정: **hand-config pipeline** 으로 통일 (2026-05-17).
