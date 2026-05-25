# 2026-05-25 사용자 알림 end-to-end 깨짐 incident

작성: 2026-05-25  
관련: ADR 0006 (폴링↔발송 분리), ADR 0016 (per-site isolation), commit `cfecac3` (progressive upsert).

## 1. 증상

사용자 (channel 1486295620044984403, 5 sub: dcinside-mgallery_chokaguya / reddit_CosmicPrincess / naver-cafe_gutterlife / scholar-google / humblebundle) 가 **오늘(2026-05-25) 새 글이 올라왔는데 봇이 "📭 새 공지 없음" 알림 보냄**. 어제까지 정상.

## 2. 진단 흐름 (잘못된 후보 → 진짜 root cause)

진단 사이 사용자가 4번 정정해야 했음. 가설 history:

1. **❌ LLM filter reject (arca trickcal 521건 다 reject)** — channel 533 만 영향, 사용자 channel 1486 와 무관. 오진.
2. **❌ sem-wait false-timeout (148 사이트)** — 부산물은 있지만 사용자 5 sub broken=1 표시의 원인은 맞으나, **알림 0건의 root cause 아님**. 보조 가설.
3. **❌ `/watch` `/list` 명령어 변경이 구독 처리 망침** — codex 정적분석 결과 add sub 정상, schema additive, corrupt path 없음.
4. **❌ lurking 사이트 fetch 시간 잡아먹음** — wall clock 영향이지만 *영속화 실패의 root cause 아님*. 별도 개선.
5. **✅ 진짜 root cause = ordering bug + cron/commit race** (아래).

## 3. 진짜 root cause

### 3a. 시간 순서

| 시각 (KST) | 사건 |
|---|---|
| 2026-05-24 08:21~08:28 | 어제 daily 폴링. *OLD 코드* (cfecac3 이전). gather 끝 후 batch sqlite upsert 정상. posts table 박힘. seen 갱신. **정상**. |
| 2026-05-25 08:20:57 | 오늘 daily cron 폴링 시작. *여전히 OLD 코드* — `cfecac3` 가 아직 commit 안 됨. seen 먼저 갱신 → `.new.json` 박음 → gather 끝 기다림 → batch upsert. |
| 2026-05-25 08:20~? | cron 폴링 *어딘가 사이트 hang*. `asyncio.gather()` 안 끝남. **batch upsert 도달 못함**. summary.txt / poll_result.json 안 박힘 (정상 종료 X). 단 `_process_site` 안의 *seen 갱신 + `.new.json` 디스크 write* 는 *gather 전*에 끝남 → **사용자 5 sub 의 seen 가 5-25 latest 까지 갱신**, sqlite 는 *비어있음*. |
| 2026-05-25 09:45 | `cfecac3` commit (progressive upsert 도입 — seen 갱신을 sqlite upsert *뒤*로 옮김). **그러나 이미 사고는 발생**. |
| 2026-05-25 09:49 | 1차 손-poll (`cfecac3` 적용 후 코드). disk seen = 5-25 latest. fetch_list → cur_ids 가 다 seen 에 있음 → `new_posts=0` → `if res["new_posts"]:` False → sqlite upsert skip. *영원히 sqlite 안 박힘*. |
| 2026-05-25 09:54 | 봇 자동 deliver_due (`bot/delivery_tick.py` 1분 tick) → posts table 사용자 5 sub 새 글 0건 → notify_empty=1 채널이라 "📭 새 공지 없음" 발송. |
| 2026-05-25 10:00~10:30 | 사용자 보고. 진단·fix 사이클. |
| 2026-05-25 10:30+ | backfill (`collected/20260525_082057/*.new.json` → posts sqlite) + `deliver_due --force-target` → 19건 발송. **사용자 복구**. |

### 3b. 두 직접 원인

**(A) OLD 코드의 ordering 버그**: `cfecac3` 이전 `scripts/poll.py` 는
1. `_process_site` 가 seen 갱신 + `.new.json` 디스크 박음
2. `asyncio.gather(*tasks)` 끝까지 대기
3. *그 후* posts sqlite batch upsert

→ gather 가 끝나지 않으면 (1 사이트 hang 등) 단계 3 도달 X. seen 만 박히고 sqlite 누락.

`cfecac3` (progressive upsert) 가 ordering 을 `.new.json → sqlite upsert → seen 갱신 → state.json` 로 바꿔 영구 fix.

**(B) cron schedule 과 commit deploy 의 race**: cron 폴링이 *commit 전*에 시작. 일반 deploy 가이드 (commit→push→N100 pull→restart) 와 cron timer 의 비동기. *2026-05-24 후반 부터 사고 fix 가 진행 중이었지만 cron 은 그 시점 코드를 그대로 실행*.

## 4. 적용된 조치 (이번 incident)

### 4a. 영속화 fix (영구)

- `cfecac3` (2026-05-25 09:45 commit): `scripts/poll.py` 의 `_process_site` 내부 progressive upsert. ordering `.new.json → sqlite → seen → state.json`. crash safe.

### 4b. 사고 사이트 보조 (영구)

- `6140b2f` (2026-05-25 10:07): sem-wait 분리. `_site_with_timeout` 가 sem 잡고 wait_for *안*에 진입 — sem queue 대기 시간이 wall cap 안에 포함 안 됨.
- `51c5307` (2026-05-25 ~9:46): `RuntimeMaxSec` → `TimeoutStartSec` (Type=oneshot 호환). systemd 외곽 안전망.
- `4673f62` (worktree merge): ADR 0016.

### 4c. 폴링 wall 단축 (사용자 결정)

- `6828f52` (2026-05-25 10:30): default 폴링 = 구독자 있는 사이트만. lurking 사이트는 `--all` 또는 `--sites` 명시 시만. 1660 → 7 사이트 (사용자 환경) → wall 412s → ~10s. seen 갱신·자가복구 가치 ≈ 0 (새 구독자 등록 시 register 가 baseline 잡음).

### 4d. 일회성 backfill (incident-only, code change X)

- `collected/20260525_082057/*.new.json` 4개 파일 (arca trickcal 20 + dcinside chokaguya 9 + naver-cafe gutterlife 2 + reddit CosmicPrincess 8) 의 39 row → sqlite `posts` INSERT OR IGNORE.
- 사용자 채널 1486 의 `last_delivered_date` 우회: `scripts/deliver_due.py --force-target channel:1486295620044984403` → 19건 digest 발송.

### 4e. 영구 게이트 (process)

- `CLAUDE.md §10` + memory `feedback-codex-delegate-use-handoff`: codex 위임 = `scripts/codex_handoff.py` + `codex_watch.py` 만. `Agent(codex:codex-rescue)` 금지 (가이드 §7 함정).

## 5. 남은 위험·후속

### 5a. cron 폴링 vs commit 시각 race

같은 사고 재현 조건: deploy 중 cron 폴링이 *commit 전 코드*로 진행 + 그 코드에 버그. 사고 fix commit 들이 cron tick 사이에 박히면 race window 발생.

**완화안 후보**:
- (i) cron 폴링 진입 시 `git rev-parse HEAD` 와 last-known-good commit 비교, 일정 시간 이내 변경됐으면 abort/delay
- (ii) deploy script 가 cron timer 잠시 stop + git pull + start (현재는 git pull 만)
- (iii) `Restart=` 또는 `OnFailure=` 로 unit 실패 시 재실행 + 알림

→ 현재 미적용. 별도 ADR 후보.

### 5b. lurking 사이트 자가복구 못함

lurking-skip default 적용 후 (`6828f52`) 구독자 0 사이트는 fetch_list 도 안 함. 그 사이트들이 *깨져도 자동 감지 X*. 새 구독자가 register 할 때 처음 확인.

→ 새 구독 → register 가 게이트. 의도된 trade-off.

### 5c. body_empty_drift 사이트

humble + naver-cafe = 본문 fetch 시 빈 글 streak 3+. 사이트 본문 비공개화 의심. dashboard `/admin/triage` 에서 점검 필요.

→ 별도 hand-config 작업.

### 5d. 영속화 검증 자동화

`collected/<ts>/*.new.json` 의 row 들이 *실제로* posts sqlite 에 박혔는지 폴링 끝에 검증 + 누락 시 자동 backfill. 현재 없음.

→ ADR 후보.

## 6. 교훈

1. **ordering 버그가 *seen-only 갱신* 으로 silent fail** — sqlite 누락 + seen 갱신 = 다음 폴링이 같은 글 안 잡음. *seen 은 sqlite 박힘 보장 후에만* 박아야 (cfecac3 ordering 이 그것).
2. **deploy timing race**: commit 전후로 cron 이 돌면 *어떤 코드가 실행되는지* 명시적 관리 필요. 특히 인프라 변경 시 cron timer stop 이 안전.
3. **incident 진단 시 사용자가 4번 정정 — 가설 분기 비싸다**. 처음 사용자 메시지 ("새 글 있는데 봇이 없다고 함") 의 *글자 그대로* 의미 = `posts table 에 글 없음` 이 root cause. 그쪽부터 보는 게 빠름.
4. **codex 위임 = handoff.py 만**. `Agent(codex:codex-rescue)` 같은 세션에서 4회 호출 — 가이드 §7 함정. 게이트 박힘.

## 7. 참고

- `docs/adr/0016-poll-per-site-isolation.md` — per-site isolation + progressive upsert.
- `docs/codex 위임 가이드.md` — codex 위임 표준 경로.
- `docs/adr/0006-per-user-delivery-time.md` — 폴링↔발송 분리.
- `output/collected/20260525_082057/` — incident 발생 시점 .new.json (4 파일, 39 row).
- commit `cfecac3` `6140b2f` `4673f62` `51c5307` `6828f52` `93520c1` — 이번 사이클의 fix 들.
