# fail 분류 카탈로그

> ⚠️ **자동 생성 — 손으로 편집 X.**
>
> source: [`bot/fail_taxonomy.py`](../bot/fail_taxonomy.py) 의 `FAIL_CATALOG`
> regen: `python scripts/gen_fail_taxonomy_doc.py`
> drift 검증: `tests/fail_taxonomy/test_doc_drift.py` (pre-push hook 자동 실행)

대시보드 `/jobs` 의 status 셀 = **fail_kind** badge + **subkind** (작은 글). 신호 의미.

## 1차 분류 (fail_kind)

| fail_kind | rc / 조건 | label | severity |
|---|---|---|---|
| `done` | rc=0 | 성공 | ok |
| `gen_fail` | rc=1 | LLM 생성·검증 실패 | error |
| `url_dead` | rc=4 (새 runs) 또는 rc=2 + tail 에 TARGET_NOT_FOUND / CERT_OR_DNS_BROKEN / SOFT_404 (옛 entries) | URL 잘못/죽음 | warn |
| `policy_reject` | rc=2 | 사이트 정책 거부 | error |
| `capability_blocked` | rc=5 | 차단(능력 부족) | warn |
| `gate_reject` | rc=3 | 휴리스틱 게이트 거부 | warn |
| `bug` | rc=-1/-2/-3/-5/-99 또는 status='failed' AND rc=0 | 시스템 결함 | error |

**pseudo-kind** (catalog 외 표시값 — `pending`/`running` 은 base status, `unknown` 은 매처 모두 미스):

- `pending` (—) · `running` (warn) · `unknown` (error)

## 2차 분류 (subkind)

- *dynamic* 표시: subkind name 이 패턴 (예: `recognizer:wikipedia_article` 처럼 capture).
- fixed subkind 가 모두 미스했을 때 dynamic 매처가 잡음 — catalog 미등록 이름도 surface.

### gen_fail

| subkind | label | hint |
|---|---|---|
| `posts_nonempty` | 추출 게시물 0건 | validator 가 게시물 추출 결과를 0건으로 판정. |
| `article_body_len` | 본문 너무 짧음 | 본문 selector 가 <100자 추출 — content selector 의심. |
| `published_at_iso` | 날짜 파싱 실패 | ISO8601 변환 실패 — date selector / format 의심. |
| `post_id_stable_shape` | post_id 형태 불안정 | post_id 가 매번 바뀌는 형태 — 새 게시물 감지 X. |
| `title_nonempty` | 제목 비어 있음 | title selector 가 빈 문자열 반환. |
| `[FAIL]:<check>` *(dynamic)* | 신규 fail_check 감지 | catalog 미등록 [FAIL] check_name — Subkind 추가 권장. |
| `llm_parse` | LLM 응답 JSON 파싱 실패 | 응답 JSON 파싱 실패 — 모델이 malformed JSON 반환 (보통 codex/큰 응답). prompt schema 강화 / 다른 모델 라우팅 후보. API 호출 자체는 성공. |
| `llm_api` | LLM API 호출 실패 | 429 RESOURCE_EXHAUSTED / UNAVAILABLE / 네트워크 오류. provider-agnostic. 구 `gemini_api` subkind 의 alias — 옛 DB row 의 'gemini 호출' 토큰도 잡음. |

### url_dead

| subkind | label | hint |
|---|---|---|
| `target_not_found` | 404 (URL 없음) | 도메인 정상이지만 입력 URL 의 글/페이지가 없음 — 카탈로그 URL 편집 필요. |
| `cert_or_dns_broken` | SSL/DNS 깨짐 | 도메인 자체 접근 단계 이전에 cert/DNS fail — 사이트가 사라졌거나 운영 오설정. |
| `soft_404` | soft-404 (200 not-found) | HTTP 200 이지만 not-found shell — URL 이 잘못됐거나 삭제됨. |

### policy_reject

| subkind | label | hint |
|---|---|---|
| `login_required` | 로그인 필요 | 사이트가 로그인 요구 (네이버카페 비공개 등). |
| `blocked_bot` | 봇 차단 | User-Agent 또는 행동 기반 봇 감지. |
| `blocked_ip` | IP 차단 | IP/네트워크 단위 차단. |
| `blocked_geo` | 지역 차단 | 지역(GEO) 단위 차단. |

### capability_blocked

| subkind | label | hint |
|---|---|---|
| `cloudflare` | Cloudflare 챌린지 | Cloudflare anti-bot 챌린지 — stealth 어댑터로 재도전. |
| `baseline_blocked` | 정적·headless 진입 차단 | static·headless 둘 다 차단 — anti-bot 의심. stealth 재도전. |
| `probe_memory_guard` | probe RSS watchdog self-kill | probe 가 RSS 임계 초과해 자기-kill (heavy SPA OOM blower 추정). stealth 대상 X — root-cause 는 별도 (probe 메모리 누적 지점 tracemalloc 조사). |
| `entry_blocked` | 진입 차단(미분류) | anti-bot/captcha 추정 — verdict 미분류. stealth 재도전 후보. |

### gate_reject

| subkind | label | hint |
|---|---|---|
| `recognizer:*` *(dynamic)* | recognizer fast-path 거부 | 특정 사이트 인식기가 fast-path 로 거부 (예: wikipedia_article). |
| `nav_only` | nav-only same-host | 단일 article 인데 nav 만 같은 host 로 발산. |
| `meta_diverging` | meta 선언 + 발산 | 단일 article + meta 선언이지만 first_article 발산. |
| `multi_host_hub` | multi-host hub root | 외부 host 여러 곳으로 발산하는 hub root. |
| `root_marketing_homepage` | root 마케팅 랜딩 | 메이저 미디어/플랫폼 root 도메인 — board 아님. 카테고리 URL 권장. |
| `board_shape` | 게시판 형식 아님 | post 리스트 구조 인식 실패. |
| `classifier_reject` | 분류기 비-게시판 판정 | LLM page-type 분류기가 content/catalog 등 비-게시판으로 판정해 거부 (ADR 0007 accept-path / ADR 0011 catalog=아티팩트·비최신순 listing). 수동 config 는 허용. |

### bug

| subkind | label | hint |
|---|---|---|
| `chromium_lock_timeout` | Chromium 락 대기 초과 | 동시 register 가 락 대기로 timeout — concurrency 제한 확인. |
| `subprocess_timeout` | register.py 600s timeout | subprocess 실행 시간 초과. |
| `subprocess_exception` | subprocess 예외 | register.py 안 예외 (외부 runner 가 catch). |
| `attempts_limit` | 재시도 한도 초과 | BUG 마커로 재시작 한도 도달. |
| `worker_exception` | worker 예외 | worker.py 본체 예외 (KeyError 등). |
| `registered_but_no_state` | subprocess 성공 / state.json 미작성 | rc=0 인데 status='failed' — state 작성 race. |
