# fail 분류 (`fail_kind`/`fail_subkind`) — 읽을 때 파생, DB 컬럼 X

## Context

`jobs.status` 의 CHECK 제약은 `pending/running/done/failed` 4값 — `failed` 한 버킷에 다음이 다 들어감:

- LLM gen+검증 4회 실패 (rc=1, `.FAILED.json`)
- policy_check 거부 — LOGIN_REQUIRED / BLOCKED_BOT/IP/GEO (rc=2, `.REJECTED.json`)
- gate 거부 — recognizer fast-path / nav_only / meta_diverging / multi_host_hub / board_shape (rc=3, `.REJECTED.json`)
- 시스템 결함 — chromium_lock timeout / subprocess timeout / 외부 예외 / worker 예외 (rc=-1/-2/-3/-99, `.BUG.json`)

대시보드 `/jobs` 가 "왜 실패?" 구분 못 함 — 각 잡 클릭해서 `result_tail` 들춰야 함. 사용자 요청: 1차 카테고리 셀 표시 + 2차 sub (subkind) 보임.

ADR 0001 이 `.BUG.json` 마커를 `.FAILED.json`/`.REJECTED.json` 과 따로 두는 결정 박음 — 같은 맥락에서 fail 분류 *표시 층* 결정 박는다.

## Decision

`bot/fail_taxonomy.py` 신설 — pure 함수 `classify_fail(status, rc, tail) -> (fail_kind, fail_subkind)`. dashboard 가 `recent_jobs()` 결과 각 row 에 두 필드 *읽을 때* 채워 넣음. DB 스키마 변경 X, backfill X.

- **1차 (rc 단독, deterministic)**: `done`(0) / `gen_fail`(1) / `policy_reject`(2) / `gate_reject`(3) / `bug`(-1/-2/-3/-99)
- **2차 (`result_tail` regex)**: gen_fail → `posts_nonempty` 등 `[FAIL] <check>` / policy_reject → `login_required` / `blocked_bot/ip/geo` / gate_reject → `recognizer:<name>` / `nav_only` / `meta_diverging` / `multi_host_hub` / `board_shape` / bug → rc 직접 매핑
- **표시** (`/jobs` + `/jobs/{id}`): 셀 1줄 = badge (1차, filter 와 일치), 셀 2줄 = 회색 작은 글 (subkind), hover/title = raw `result_tail` 마지막 줄. filter dropdown 은 1차 5값만 평탄화.

## Why

derive 가능 = `result_tail` 안에 `register.py` 의 안정적 print 라인 (`등록 거부 — multi-host hub root` / `[FAIL] article_body_len` 등) 이 다 들어있다 (`bot/site_ops.py:226` 가 last ~4000 chars 보존). `worker.py` 도 rc=-1/-2/-3/-99 에서 tail 명시 채움. column 추가 비용 (마이그 + backfill) 대비 derive 의 perf 비용 (페이지 당 ≤200 row × regex 10줄 = µs) 무시할 수 있음.

분류 룰이 *진화 빠름* — 새 gate (`multi_host_hub` 가 2026-05 추가됐듯) 늘면 컬럼 값 enum 도 같이 마이그 필요. derive 면 룰 한 파일 (`bot/fail_taxonomy.py`) 만 수정 → 기존 행 즉시 새 분류 적용.

## Considered Options

- **DB 컬럼 `fail_kind`/`fail_subkind` 저장** — `mark_job_finished` 시점에 채움. perf 빠름·indexable. 기각: ALTER TABLE + 수만 행 backfill, 분류 룰 진화 마다 재backfill, `recent_register_jobs` 가 항상 LIMIT/OFFSET 이라 perf 이득 의미 적음.
- **`register.py` 가 종료 시 sentinel JSON 한 줄을 `result_tail` 끝에 박음** — dashboard 가 그 줄만 파싱. 기각: register 의 모든 종료 경로 (rc=0/1/2/3 + worker 의 rc=-1/-2/-3/-99) 다 손대야 함, tail truncate (4000 chars) 직전에 sentinel 잘릴 가능, 깨지기 쉬움.
- **분류 함수를 `dashboard/fail_taxonomy.py` 에 둠** — dashboard 만 쓴다 시그널. 기각: 미래 `bot/inspector.py:format_recent_jobs` (Discord `/admin recent`) · `bot/site_ops.py` 등도 같은 분류 쓸 가능, dashboard → bot 역방향 import 어색.
- **분류 함수를 `bot/inspector.py` 안 헬퍼로** — 신파일 X. 기각: inspector.py 이미 ~700줄, 단일 책임 흐림, test 작성 시 inspector deps 다 끌고 옴.
