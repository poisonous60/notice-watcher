# 발송 시각 = per-user 설정, 폴링과 분리 — realtime 폐지

## Context

지금까지 발송 모델은 **realtime** 단일 모드였다: `poll_and_notify.py` 가 폴링(`poll.py`) 직후 곧바로 `notify.py --no-digest` 를 호출해 새 글을 즉시 요약·필터·Discord 발송. 모든 구독의 `subscriptions.schedule` 컬럼은 `'realtime'` 으로 강제 마이그(`db.py` `_migrate`). 사용자는 받을 시각을 못 정함.

이 모델 자체가 **왕복 이력**이 있다 — 더 옛날엔 per-sub `HH:MM` digest(폴링 1회/일 + 발송 timer 15분이 사용자 schedule 시각 도래분만 flush, `pending`/`digest_sent` 테이블). 그게 realtime 으로 한 번 갈아엎혔다(C10 문서가 옛 digest 모델을 설명하나 코드는 이미 realtime). 그래서 "왜 또 시각 선택으로 돌아가나" 가 의아할 수 있어 기록한다.

재검토 계기: batch 로 사이트 100개씩 register 하며 *폴링(특히 list-fetch)이 생각보다 싸다*는 관찰. 등록 config 83개 중 ~80%가 httpx(가벼운 list fetch), chromium 전략(playwright_html 8 + ArcaLive)은 소수. 폴링을 시간당으로 올려도 부담이 크지 않음 → 신선한 데이터를 자주 모아두고, **발송 시각만 사용자가 고르게** 하는 게 가능해졌다.

핵심 개념 분리: **폴링 캐던스(사이트별 공유, 데이터 신선도)** 와 **발송 시각(수신처별, 사용자 선택)** 은 독립 축이다. "폴링이 싸다"는 통찰은 *공유 폴링 빈도*를 올릴 근거지, 사용자마다 같은 사이트를 중복 폴링할 근거가 아니다. 폴링은 사이트당 1회로 모든 구독자가 공유한다(중복 fetch 0).

## Decision

발송 시각을 **수신처별 설정**으로 분리하고 **realtime 모드를 폐지**한다. 발송 모드는 `HH:MM` 하나뿐.

- **시각 범위**: DM = `user_settings(user_id)`, 채널 = `channel_settings(channel_id)`. per-subscription 아님 — 사용자/채널이 *모든* 구독을 자기 시각에 한 묶음으로 받는다. 채널 시각은 Manage-Channel 권한자만 설정(채널은 공유 게시판 → 한 채널 = 한 시각 = 한 묶음 발송이 일관적).
- **기본 08:30 KST**, 기존 전원 마이그. realtime 선택지 없음.
- **폴링/발송 완전 분리**: 폴링(시간당, `config.toml` 전역값)은 새 글을 `posts` 저장소에 raw 로만 수집(LLM 0). 발송은 별도.
- **저장 = `posts`(raw + lazy summary + TTL ~7일 GC) + `deliveries` 네거티브 스페이스**. 발송창 job = `posts ⨝ (대상 구독 slug) − deliveries(대상)` = 빚진 글. 옛 `pending` fan-out 도, `collected/` 재스캔도 불필요. 요약은 발송창에서 처음 필요할 때 1회 계산해 `posts.summary` 캐시(여러 발송창이 재사용 → 중복 LLM 0).
- **발송 메커니즘 = 봇 내부 1분 tick**. systemd 외부 타이머 아님. 매분 due 대상을 **SQL 쿼리**로 골라냄(`deliver_at` 인덱스, `deliver_at <= now_kst_hhmm AND (last_delivered_date IS NULL OR last_delivered_date < today_kst)`). 사용자 수 무관(메모리 루프 X). flush 후 `last_delivered_date = today`. 봇 다운 후 부팅 시 같은 조건이 놓친 창을 catch-up.
- **레거시 제거**: `subscriptions.schedule` 컬럼, `pending`·`digest_sent` 테이블, `flush_digests`/`digest_chunks`.
- `notify_empty` 유지 — 의미 그대로 발송창 기준으로 재배선("오늘 새 공지 없음" 한 줄).
- UI: 슬래시 `/notify-time [HH:MM]` 옵션 커맨드(인자 없으면 현재 설정 조회). 채널에서 권한자가 치면 채널 설정.

## Consequences

- **realtime 셀링포인트 상실** — 가장 빠른 사용자도 다음 발송창까지 대기. 낮에 올라온 글은 다음 아침 digest. 하루 1회 발송의 본질적 지연(최대 ~24h)이며 폴링 빈도와 무관. 의도된 트레이드오프(사용자가 받음).
- **분 단위 정확** — 옛 15분 격자 불만(37분 설정→37분에 안 옴) 해소. 봇 내부 tick + 분 해상도.
- **발송이 봇 가동시간에 의존** — 봇 다운 = 그 분 발송 안 됨. 부팅 catch-up 으로 손실 방지(digest 손실보다 늦게라도 받음).
- **시간당 폴링의 가치 = 흩어진 발송 시각**. 단일 시각 사용자만 보면 과하나 무해; 사용자 시각이 퍼지면 각 발송창이 신선한 데이터를 받음.
- 스키마 마이그(컬럼/테이블 DROP)는 되돌리기 비쌈 — 새 경로 검증 후 단계적으로.

## Review refinements (codex, 구현 전)

- **[CRITICAL] 백로그 폭탄 가드**: 빚진글 쿼리는 `posts.collected_at >= subscriptions.created_at` 하한 필수. 신규 구독자가 slug 의 과거 글을 한꺼번에 받지 않게.
- **forward-only(의도)**: `posts` 는 폴링이 *새로* 본 글만 채움(`seen_post_ids` 에 없던 것). 마이그 이전·lurking 글은 `posts` 에 없음 = 백로그 안 함이 의도. 신규 구독자는 구독 후 새 글부터.
- **[HIGH] event loop 비블록**: 발송 flush(LLM 요약·blocking Discord·`time.sleep`)를 1분 tick 의 asyncio 루프에서 직접 돌리지 말 것 — `asyncio.to_thread` 또는 subprocess 오프로드. tick 자체는 due 쿼리만(가벼움).
- **[HIGH] 채널 OR 보존**: flush 를 `target_id` 단위 grouping → 그 채널 구독자들의 필터를 한 pass 에서 OR → 1회 발송 + 1회 `deliveries` mark. (현 notify Phase C 의미 그대로. deliveries 가 channel 단위라 naive 하게 per-subscriber 마스크로 쓰면 두 번째 구독자 필터가 억제됨.)
- **[HIGH] 마이그 순서**: `subscriptions.schedule` 컬럼 **즉시 DROP 안 함** — reader(`/watch`·worker success·notify) 먼저 새 경로로 제거한 뒤 후속 cleanup 마이그에서 DROP. 중간 배포창 크래시 방지. `pending`/`digest_sent`/`flush_digests` 도 reader 제거 후 제거.
- **[MEDIUM] TTL GC 가드**: TTL(7d) ≫ 발송지연(~1d) 라 기본 안전하나, GC 는 "그 글의 모든 구독 대상이 `deliveries` 에 있음" 도 추가 조건으로(미수신 글 삭제 방지). 봇 장기 다운 대비.
- **[MEDIUM] 마이그 원자성**: `_migrate` 의 ADD/DROP 을 한 트랜잭션 경계로, 부분 실패 시 롤백.
- **[LOW] KST 일관**: `last_delivered_date`·`today_kst`·due 비교 전부 KST 계산(`_now_iso()` UTC 직이식 금지). 자정 전후 멱등 깨짐 방지.
- **catch-up 한계(수용)**: 봇이 자정~`deliver_at` 사이 부팅 시 전날 놓친 창 catch-up 못함(`deliver_at <= now` false). 놓친 날 digest 는 다음 날 창으로 흡수(posts TTL 내 생존). 수용.

## Alternatives considered

- **per-subscription 시각**: 같은 채널에 다른 시각이 섞여 묶음 발송 일관성 깨짐. 거부 — 시각은 수신처(사용자/채널) 단위.
- **realtime 유지(기본만 HH:MM)**: 모드 2개 유지. 거부 — 사용자가 단순화 위해 폐지 선택.
- **저장 B(`pending` per-target fan-out)**: 글 1개 × 대상 N row. `posts`+네거티브 스페이스가 write 증폭 없이 같은 결과 → 거부.
- **요약 폴링 시점 계산**: lurking·필터 탈락 글까지 요약 낭비. 거부 — 발송창 lazy + 캐시.
- **systemd 15분 타이머(옛 방식)**: 분 정확 불가. 거부 — 봇 내부 1분 tick.
