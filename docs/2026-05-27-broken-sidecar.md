# `.BROKEN.json` health sidecar + 사용자 알림 + 복구 파이프라인

작성: 2026-05-27. 세션 commit `255ef1b` (rev2) + `7669bbe` (rev3).

> 버그 시 참고용 — 어디 손대면 뭐 깨지는지 + 왜 이렇게 설계됐는지.

## 0. TL;DR

`output/poll_state/<slug>.BROKEN.json` = 새 health sidecar 카테고리.
**blocking marker 아님** (`is_blocked` 무관). polling/reprobe/delivery 그대로 살아있고,
deliver_due 가 사용자 향 알림 안에 inline / footer 로 표시.

35 broken slug (cb>0) 중 zombie loop 9 + stale FAILED 5 발견 → 봉합. 진짜 broken 4건이
`/triage/broken` 큐에 노출. 사용자가 dashboard 에서 `📋 복사` → Claude Code 붙여넣기 →
복구 진행.

## 1. 배경 (원인)

snapshot 2026-05-27 19:51:

- `consecutive_breakage > 0` slug = **35건**
- 그 중 **zombie loop 9건** — `status-deno cb=9` 가 대표. reprobe rc=0 9번 성공인데 cb 계속 누적.
- 그 중 **stale FAILED 5건** — `watchuseek cb=15` 가 대표. state.json + .FAILED.json 동시 존재.
- 사용자 알림 **0** — 등록한 board 가 며칠째 깨져도 침묵.

### 1a. zombie 패턴

```
poll → 깨짐 → cb += 1 → reprobe enqueue
worker reprobe → register.py 재실행 → rc=0 (등록 재성공)
*** cb reset 안 됨 *** (worker.py:637 success path 가 _post_register_success 만 호출)
다음 poll → 같은 이유로 또 깨짐 → cb=N+1 → 무한 반복
```

reprobe rc=0 이라 `_reprobe_fail_streak` = 0 → `.BUG.json` 자동 게이트 못 발동.

### 1b. stale FAILED

```
옛날 자동등록 실패 → .FAILED.json 박힘
사용자가 /watch 또는 batch 로 재시도 → state.json 박힘 (등록 성공)
*** .FAILED.json 안 지워짐 *** (특정 path 에서 sibling cleanup 빠짐)
is_blocked(slug) = True → reprobe job 들이 worker 진입 시점 rc=-7 fast-skip
poll.py 가드 (poll.py:441) 도 reprobe enqueue 차단 → 자체 복구 불가능
하지만 polling 자체는 _load_states 가 state.json 만 보고 진행 → cb 계속 증가
```

## 2. 설계 결정 (codex review rev1 → rev2 → rev3)

### 2a. BROKEN ≠ blocking marker

- `marker_kind` 우선순위 = `rejected > bug > failed` **3종 그대로**. BROKEN 안 넣음.
- `is_blocked(slug)` 도 BROKEN 안 봄.
- 별도 API: `is_broken(slug)` / `broken_info(slug)` / `broken_slugs()`.

근거: BROKEN 은 *health 신호* — 차단 결정 아님. `is_blocked` 에 넣으면
`/preview`·`/watch`·worker fast-skip 다 막힘 → polling 자체가 죽음. 사용자 의도
("polling 계속 + 사용자에 알림") 위반.

### 2b. State scanner BROKEN suffix exclusion (HARD-STOP 배포 순서)

`.BROKEN.json` 도입 *전* 에 모든 `*.json` glob scanner 가 BROKEN suffix exclude
하도록 코드 먼저 배포. 안 그러면 `_load_states` 가 BROKEN payload 를 normal state 로
파싱 시도 → 봇 crash.

배포 순서:
1. state scanner exclusion 코드 commit + N100 deploy
2. `_save_broken` write 호출 박는 코드 + migration script commit + N100 deploy
3. N100 migration 실행 (`output/poll_state/` tar backup 후 zombie 정리 + real broken 마커 박음)

### 2c. zombie 봉합 (worker.py)

`bot/worker.py:642` reprobe success 분기 — `_clear_broken_after_reprobe(slug)` 호출.
`state.json.consecutive_breakage = 0` + `.BROKEN.json` unlink. idempotent.

### 2d. poll.py BROKEN write 3 path

`_maybe_save_broken(slug, st, note, log_lines)` 헬퍼 — `cb >= broken_threshold`
+ FAILED/REJECTED/BUG 마커 없음 일 때만 `_save_broken` 호출. 3 자리에서 사용:

1. `_process_site` 의 `res["broken"]` 분기 — 정상 poll 가 깨짐 신호 감지
2. `_site_with_timeout` 의 `chromium_lock_timeout` fallback — flock 경합 timeout
3. `_run_inner` 의 `asyncio.TimeoutError` / `BaseException` aggregator — wall timeout / task_exception

빠진 path 있으면 그 fail mode 의 broken slug 가 `/triage/broken` 안 잡힘. **fail mode 추가 시
이 헬퍼 호출 박는지 점검**. codex rev2 diff review HIGH F 가 정확히 2/3 path 누락 잡아냄.

### 2e. deliver_due 사용자 알림 (rev3 — broken 별도 메시지 0 invariant)

**rev2 에서 별도 trailing "status notice" 메시지 발송 했었음** → rev3 사용자 정정으로
*broken 만* 별도 메시지 금지. 한 메시지 안에 흡수:

| owed | notify_empty | broken | empty | 발송 |
|------|--------------|--------|-------|------|
| >0 | (any) | X | X | digest chunks (기존) |
| >0 | =1 | X | O | digest chunks + trailing empty_notice (기존 동작 보존) |
| >0 | =1 | O | X | digest chunks (마지막 chunk 끝에 broken 푸터 append) |
| >0 | =1 | O | O | digest chunks (마지막 chunk + footer) + trailing empty_notice |
| =0 | =1 | X | X | (no_subs / 빈 path) |
| =0 | =1 | X | O | `_empty_notice_content` 단일 메시지 |
| =0 | =1 | O | X | `_status_inline_content` 단일 메시지 (❗ 인라인) |
| =0 | =1 | O | O | `_status_inline_content` 단일 메시지 (❗ + 📭 mix) |
| =0 | =0 | (any) | (any) | 발송 0 |

**invariant**: broken 슬러그만으로 별도 `deliver()` 호출 절대 X.

`digest_chunks(max_len=1850 - footer_reserve)` 로 마지막 chunk 가 푸터 포함해 Discord
2000자 cap 안에 들어가게. broken 슬러그 많으면 footer 안에서 "외 N건 dashboard 확인"
잘림 (`_broken_footer_for_digest(max_chars=400)`).

발송 직전 `_recheck_broken` 2 자리 (owed=0 inline 직전 + owed>0 footer 빌드 직전) —
reprobe rc=0 가 그 사이 BROKEN unlink 한 경우 race 가드.

### 2f. dashboard `/triage/broken` + 복구 프롬프트

- **list 표시**: 큐 행 — slug, cb, count, last_status, 구독자, first/last_at, url.
  정렬: cb DESC, same cb 면 last_at DESC, same 면 slug ASC. (rev3 codex LOW finding 반영)
- **bulk 프롬프트**: `prompts.broken_recover_bulk(items)` — `/triage/broken` 상단 `📋 복사`
- **per-slug 프롬프트**: `prompts.broken_recover_slug(slug, url, cb, last_status, ...)` —
  `/subs/<slug>?from=broken` 상세 (BROKEN 마커 있을 때만 카드 노출)
- **snapshot clear 버튼**: dev box snapshot 만 unlink. N100 영향 X (다음 pull 가 복원).
  운영 정리 = N100 `migrate_broken_zombie.py --clear-all --yes` 또는 hand-fix → 자가 복구.

## 3. 복구 파이프라인

```
[N100 poll cycle]
  cb += 1 (broken signal)
  cb >= broken_threshold (기본 3, config.toml override 가능)
  → _save_broken (.BROKEN.json)
                                        ┐
[N100 deliver_due tick]                  │
  owed>0 → digest 마지막 chunk 끝에 푸터 │ ← 자동 (사용자 향)
  owed=0 + notify_empty=1 → inline ❗    │
  owed=0 + notify_empty=0 → 메시지 X     │
                                        ┘
[사용자 Discord]
  digest 받으면서 푸터 봄  or  inline ❗ 받음
                                        ┐
[dev box dashboard /triage/broken]      │
  큐 표 — cb 큰 거 위로                  │ ← 사람-개입 (자가 복구 실패 시)
  📋 복사 (bulk 또는 per-slug 프롬프트)  │
                                        ┘
[Claude Code 붙여넣기 — dev box]
  0. live 확인 (curl -sI 또는 browser)
  1. probe artifact pull (triage.py pull --slug)
  2. last_status 별 가설:
     - poll_timeout → SPA / chromium hang / 새 anti-bot
     - chromium_lock_timeout → flock 경합 (per-site 문제 아닐 수도)
     - reprobe_enqueued → zombie 후보 또는 reprobe 도 같은 fail
  3. Track B 일반화 (probe / prompt / engine) 1순위
     Track A (slug-specific config) 는 최후
  4. probe_smoke --stage 3 --stage 5 PASS
  5. docs/cases/<slug>.md 작성 (improved / handcrafted / no_change)
  6. git commit + push (pre-push probe_smoke 통과 의무)
  7. ssh $DEPLOY_HOST 'bash ~/notice-watcher/scripts/n100_deploy.sh'
                                        ┐
[N100 다음 poll]                        │
  정상 fetch → broken=False             │ ← 자가 복구 자동
  → cb = 0 reset                        │
  → .BROKEN.json unlink                 │
                                        ┘
[N100 다음 deliver_due]
  broken sidecar 없음 → 정상 digest (푸터 / ❗ 사라짐)
```

자가 복구 (reprobe rc=0) 가 1차. dashboard 프롬프트 + Claude 는 자가 복구 실패 시 사람-호출.

## 4. 파일별 영향 (버그 났을 때 어디 봐야 하나)

| 파일 | 역할 |
|------|------|
| `bot/runtime_config.py:52` | `broken_threshold: int = 3` default |
| `config.toml:20` | `[poll] broken_threshold = 3` override |
| `bot/site_ops.py:88` | `_ALIAS_MARKER_SUFFIX` (`.BROKEN.json` 포함) |
| `bot/site_ops.py:175-237` | `is_broken` / `broken_info` / `broken_slugs` / `_clear_broken_after_reprobe` |
| `bot/worker.py:642` | reprobe success 분기 — `_clear_broken_after_reprobe` 호출 |
| `scripts/register.py:1721+` | `_save_broken` / `_clear_broken` / `_list_broken` |
| `scripts/register.py:1303` | `_save_state` sibling cleanup — `.BROKEN.json` 포함 |
| `scripts/register.py:1607` | `_save_bug` sibling cleanup — `.BROKEN.json` 포함 |
| `scripts/register.py:1545` | `_save_rejected` sibling cleanup — `.BROKEN.json` 포함 |
| `scripts/poll.py:339` | `_maybe_save_broken` 헬퍼 — 3 path 공통 |
| `scripts/poll.py:344-348` | `_load_states` suffix exclusion |
| `scripts/poll.py:431-435` | `_process_site` broken 분기 → `_maybe_save_broken` |
| `scripts/poll.py:735-740` | `chromium_lock_timeout` fallback → `_maybe_save_broken` |
| `scripts/poll.py:920-924` | `_run_inner` wall-timeout / task_exception aggregator → `_maybe_save_broken` |
| `scripts/poll.py:484-494` | 정상 fetch path — cb=0 + `.BROKEN.json` unlink (자가 복구) |
| `scripts/deliver_due.py:71-77` | `_empty_notice_content` (보존 — broken 만 ban) |
| `scripts/deliver_due.py:80-117` | `_status_inline_content` (owed=0 단일 메시지) |
| `scripts/deliver_due.py:119-144` | `_broken_footer_for_digest` (owed>0 마지막 chunk append) |
| `scripts/deliver_due.py:225-260` | owed=0 path 분기 |
| `scripts/deliver_due.py:262-322` | owed>0 path + footer reserve + trailing empty_notice (broken 만 ban) |
| `dashboard/state.py:155-189` | `broken_slugs` / `broken_payload` / `state_file_slugs` suffix exclusion |
| `dashboard/app.py:357-395` | `/triage/broken` 라우트 + bulk prompt 전달 + sort cb DESC → last_at DESC → slug ASC |
| `dashboard/app.py:397-426` | `/triage/broken/clear` (snapshot only — N100 영향 X) |
| `dashboard/app.py:773-795` | `/subs/<slug>` 의 `broken_payload` + `p_broken` prompt-card |
| `dashboard/prompts.py:281-329` | `broken_recover_slug` per-slug 프롬프트 |
| `dashboard/prompts.py:332-385` | `broken_recover_bulk` 일괄 프롬프트 |
| `dashboard/templates/triage_broken.html` | 큐 표 + `📋 복사` bulk card + snapshot clear 안내 |
| `dashboard/templates/sub_detail.html` | BROKEN payload box + `❗ BROKEN 복구` prompt-card |
| `dashboard/templates/triage.html` | 홈에 `BROKEN 큐 (수동 정리)` 카드 |
| `dashboard/templates/subs.html` | `/subs` 행에 BROKEN 뱃지 (`broken_marker`) |
| `scripts/migrate_broken_zombie.py` | dry-run / yes / clear-all + tar backup. zombie/real_broken/transient/noop 분류 |
| `scripts/generate_site.py:40` | `POLL_SUFFIXES` 에 `.BROKEN.json` 등록 (정적 site generator) |
| `scripts/prune_orphans.py` | orphan 마커 prune 에 BROKEN 포함 |
| `scripts/register_batch.py:64` | `MARKER_SUFFIXES` 에 `.BROKEN.json` |
| `scripts/migrate_slug_schema.py:56` | slug rename 시 `.BROKEN` 도 함께 rename |
| `bot/inspector.py:594-600` | `/admin status` glob 가드 |
| `bot/admin.py:99-110` | `/admin status` 카운터 |
| `dashboard/clustering.py:58-60` | clustering scanner suffix exclusion |
| `dashboard/candidates_view.py:186-188` | candidates scanner suffix exclusion |

## 5. 테스트 (회귀 anchor)

- `tests/bot/test_broken_marker.py` — `_save_broken`/`_clear_broken` round-trip, `is_blocked` invariant, `is_registered` invariant, sibling cleanup
- `tests/bot/test_zombie_reset.py` — reprobe rc=0 → cb=0 + BROKEN unlink
- `tests/bot/test_delivery.py::flush_broken_owed_pos_footer_in_digest` — owed>0 path 단일 메시지 + 푸터
- `tests/bot/test_delivery.py::flush_broken_owed_zero_inline_only` — owed=0 path 단일 메시지 inline
- `tests/scripts/test_poll_broken_threshold.py` — `_maybe_save_broken` 3 path (low cb skip / timeout write / priority marker guard / chromium_lock payload)
- `tests/scripts/test_deliver_due_broken.py` — `_status_inline_content` / `_broken_footer_for_digest` / cap overflow / rev3 invariants
- `tests/dashboard/test_triage_broken.py` — route 200 + state helpers + suffix exclusion

probe_smoke stage 3+5 PASS 1718 cases @ `7669bbe`.

## 6. 흔한 버그 시나리오 (예방용)

### 6a. "broken sidecar 박았는데 사용자한테 알림 안 가요"

체크:
1. 그 slug 구독자 있나? `bot.sqlite3` `subscriptions WHERE slug=<slug>`
2. 구독자 중 `notify_empty=1` 있나? notify_empty=0 인 구독자는 broken 알림 안 받음 (의도)
3. deliver_due cron 도는지? `/runs` dashboard 페이지
4. `is_broken(slug)` True 인지? `output/poll_state/<slug>.BROKEN.json` 존재 확인

### 6b. "별도 broken DM 갑니까?"

NO. rev3 invariant — broken 만 별도 `deliver()` 호출 절대 X.
- owed>0 → digest 마지막 chunk *안에* 푸터
- owed=0 → 기존 empty_notice 자리 inline replace (메시지 1개)
- 별도 trailing message = `_empty_notice_content` (broken 아닌 empty 만)

### 6c. "broken sidecar 자체 복구 안 됨"

체크:
1. reprobe 가 도는지? `/jobs` dashboard 또는 `bot.sqlite3` `jobs WHERE kind='reprobe' AND slug=<slug>`
2. reprobe rc=0 인데 cb 안 줄어드는지? → zombie 의심. worker.py:642 `_clear_broken_after_reprobe` 호출 확인. `last_status="reprobe_recovered"` 박혔는지 state.json 봄
3. reprobe rc≠0 이면 → 다음 cycle 또 시도. `reprobe_fail_streak_limit` (3) 도달 시 BUG 마커 박힘 → 그 후 reprobe 차단
4. FAILED/REJECTED/BUG 동반 있나? 그러면 BROKEN write skip — 우선순위 마커가 final 결정. stale 의심이면 migration `--clear-all` 후 자가 복구 대기

### 6d. "디제스트 마지막 chunk 가 Discord cap 2000자 넘어 발송 실패"

체크:
1. broken 슬러그 너무 많아서 푸터 길어졌나? `_broken_footer_for_digest(max_chars=400)` 이 cap. 넘으면 "외 N건" 잘림
2. `digest_chunks(max_len=1850 - footer_reserve)` 의 footer_reserve 계산 빠뜨림? `_flush_target_inner` 의 `chunks = digest_chunks(owed, max_len=1850 - footer_reserve)` 확인

### 6e. "snapshot pull 후에 BROKEN 가 사라졌다 나타났다 함"

snapshot 은 N100 의 *시점 사본*. N100 가 자가 복구하면 sidecar 빠짐. 다시 깨지면 또
박힘. 정상 동작. dashboard `/triage/broken` 의 `📋 복사` 프롬프트는 *snapshot 시점* 데이터
— Claude 실행 시점에 다시 `triage.py pull --slug` 로 최신 확인.

### 6f. "dev box dashboard 의 `snapshot BROKEN clear` 눌렀는데 N100 변화 X"

의도된 동작. snapshot 한정 정리 (dev box `output/snapshot/poll_state/*.BROKEN.json` unlink).
N100 의 원본 `output/poll_state/*.BROKEN.json` 은 그대로. 다음 `inspect_subs.py pull` 시
N100 원본 다시 가져옴. 운영 정리는 N100 의 `scripts/migrate_broken_zombie.py --clear-all
--yes` 또는 hand-fix 후 자가 복구 대기.

### 6g. "is_blocked(slug) 가 True 인데 polling 계속 도는 듯"

BROKEN-only 상태이면 `is_blocked` = False, polling 계속. `is_blocked` True 면 FAILED/
REJECTED/BUG 중 하나. 그 경우 `_load_states` 가 state.json 만 보고 (마커 무시) 폴링 계속.
`poll.py:438-455` 의 reprobe enqueue 가드가 마커 보고 reprobe 차단.

이런 경우 = stale state — `_save_*` path 어딘가에서 state.json 안 지움. 일반적으로
`_save_rejected`/`_save_bug` 는 state.json sibling cleanup 함. 안 지우는 path 발견 시
거기 sibling cleanup 추가.

## 7. 운영 명령 cheatsheet

```bash
# dry-run (N100 변경 X)
ssh $DEPLOY_HOST 'cd ~/notice-watcher && .venv/bin/python scripts/migrate_broken_zombie.py --dry-run'

# 실행 (tar backup 자동)
ssh $DEPLOY_HOST 'cd ~/notice-watcher && .venv/bin/python scripts/migrate_broken_zombie.py --yes'

# rollback (BROKEN sidecar 전부 unlink)
ssh $DEPLOY_HOST 'cd ~/notice-watcher && .venv/bin/python scripts/migrate_broken_zombie.py --clear-all --yes'

# threshold 조정 (인스턴스별)
# config.local.toml 에 박음:
# [poll]
# broken_threshold = 5     # 더 보수적 (5회 이상만 알림)
# 또는 999 (사실상 비활성화)
# 변경 후 봇/폴링 재시작 필요

# 현재 BROKEN 큐 N100 에서 직접 확인
ssh $DEPLOY_HOST 'ls ~/notice-watcher/output/poll_state/*.BROKEN.json | wc -l'
ssh $DEPLOY_HOST 'ls ~/notice-watcher/output/poll_state/*.BROKEN.json'
```

## 8. 관련 ADR

- **ADR 0001** "재시도 안 함" — BROKEN 도 자동 재박음 없음, health 표시일 뿐. reprobe 가 자가 복구 시도하고 실패 누적 시 BUG 마커 박혀 자동 차단.
- **ADR 0006** per-user 발송 시각 — `deliver_due` HH:MM digest path 에 broken 인라인 흡수.
- **ADR 0015** worktree 격리 — 본 작업 `session-broken-queue` (rev2) + `session-broken-prompts` (rev3) 모두 worktree.
- **ADR 0018** cron×commit race 가드 — N100 deploy 는 `n100_deploy.sh` 사용 (raw `git pull` 금지).

## 9. session 이력 (commit 추적)

| commit | 내용 |
|--------|------|
| `255ef1b` | rev2 — `.BROKEN.json` 도입 + state scanner exclusion + zombie 봉합 + 별도 status notice (rev3 에서 삭제됨) + migration |
| `255ef1b` 직후 N100 deploy | 5 zombie 정리 + 4 real_broken 마커 박음 |
| `7669bbe` | rev3 — threshold 6→3 + config.toml 노출 + deliver_due 재작성 (별도 message 폐기, 푸터/inline) + dashboard 복구 프롬프트 + `/triage/broken` 정렬 fix |
| `7669bbe` 직후 N100 deploy | threshold=3 적용 |

## 10. codex 검토 history

- **rev1 plan review** (codex) → HARD-STOP G (deploy 순서), HIGH A/D/E/F/I → rev2 plan
- **rev2 diff review** (codex) → HIGH F (timeout fallback paths 누락) + LOW A + MED H/I → fix commit
- **rev3 plan review** (codex) → A HIGH (inline transition), D MED (broken_recover_slug frame), E HIGH (bulk prompt), H MED (case), I HIGH (threshold/config) → rev3 plan
- **rev3 diff review** (codex) → A-G/I-K PASS, H LOW (sort 주석 mismatch) → fix commit `c7f603e`

review 결과 파일:
- `output/codex_generic_codex-review-broken-plan-task_prompt.result.md`
- `output/codex_generic_codex-review-broken-diff-task_prompt.result.md`
- `output/codex_generic_codex-review-broken-rev3-task_prompt.result.md`
- `output/codex_generic_codex-review-rev3-diff-task_prompt.result.md`

(원본 plan: `output/_plan_broken_queue.md` (rev1/rev2) + `output/_plan_broken_rev3.md`)
