Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.


## 2. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 3. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.


# CLAUDE.md — notice-watcher
## 1. 두 머신 모델 — dev box ↔ N100

| 머신 | 역할 | 변경 가능? |
|---|---|---|
| **dev box** (이 폴더 = `notice-watcher` repo dev clone) | 코드 작성·테스트·commit·push. 대시보드(`scripts/dashboard.py`) dev 전용 | YES — git commit/push, 직접 편집 |
| **N100** (`<user>@<host>` — Tailscale MagicDNS; LAN IP `<lan-ip>` 도 가능) | 봇·polling 운영 (`notice-bot.service` systemd) | NO — *코드 편집 금지*. `git pull` 만 받음 |

**핵심 원칙**: 모든 코드 변경 **dev box 에서만**. N100 *pull only*. 양쪽 같은 `git log` 유지.

## 2. 표준 배포 사이클

dev box:
```
1. 코드 작성·테스트
2. git add … && git commit -m '…' && git push origin main
   (pre-push hook 이 probe_smoke --stage 3 --stage 5 자동 실행)
```

N100:
```
3. ssh <user>@<host> 'cd ~/notice-watcher && git pull --ff-only'
4. (adapters/·engine/·scripts/notify.py·bot/ 변경 시) 'systemctl --user restart notice-bot.service'
5. (requirements.txt 변경 시) '.venv/bin/pip install -r requirements.txt' (restart 전)
```

대시보드(dev 전용) N100 *배포 안 됨*.

상세 운영: `docs/운영 메모.md` §8.

## 3. N100 코드 작업 금지 — 이유 + 안전망

### 왜 금지

N100 직접 편집 시:
- dev box 비대칭 → 다음 `git pull --ff-only` 충돌 → push 가 N100 local 변경 덮어쓸 위험
- N100 변경 *영원히 dev box 에 안 옴* (사람 잊음)
- 회수 비쌈 (stash export, patch transfer, content compare 등)

### 발생 시 안전망 (이미 한 번 — 2026-05-15 stash@{0})

N100 *실수로* 또는 *부득이* 변경 만든 경우:
1. **drop 금지** — `git stash push -u -m "n100-local-<YYYYMMDD> — <설명>"` 보존
2. dev box 다음 commit 직전 `git pull --ff-only` 멈추면 위 stash 살아있는지 확인
3. 별도 작업 — stash 분석 후 dev box 회수 또는 drop

## 4. 새 dev 박스 setup (한 번)

```
git clone https://github.com/poisonous60/notice-watcher.git
cd notice-watcher
bash scripts/setup-hooks.sh   # 또는 pwsh scripts/setup-hooks.ps1
.venv 만들고 pip install -r requirements.txt
```

`setup-hooks` 가 `.git/hooks/pre-push` 박음. 매 push 직전 `probe_smoke --stage 3 --stage 5` 강제 — FAIL 이면 push 차단. `--no-verify` **금지** — 픽스 먼저.

## 5. 양쪽 동기성 유지 룰

### 룰 A: 코드 변경 = dev box only
- bot, engine, adapters, scripts, prompts, configs, dashboard, probe, generate, … 모든 코드 *dev box 에서만*.
- N100 ssh 후 `vi`/`nano`/`sed` *금지*.

### 룰 B: N100 직접 작성 가능 = output/ 뿐
- N100 `output/` (poll_state, traces, probe artifacts, bot.sqlite3 등) *runtime* 데이터 — git 추적 X. N100 작성 자연.
- 그 외 *코드/config/docs* 항상 dev box → push → N100 pull.

### 룰 C: configs/ 변경도 dev box
- 새 사이트 등록 dev box 에서 `python scripts/register.py …` 또는 손-config + push.
- 봇 자동 등록 (`/watch` 사용자 명령) N100 에서 동작 → *N100 configs/* dev box 보다 앞서갈 수 있음 (사용자 등록).
- 이 경우 → 별도 작업으로 dev box sync (운영 메모 §8 의 `report-triage` 또는 `hand-config` 워크플로).

### 룰 D: slug schema 마이그 (전용)
- `engine/recognizers/<plat>.py` 의 `PATTERNS`/`builder`/`_slug_board` 변경하면 같은 URL slug 바뀜 → `configs/`·`output/poll_state/`·`output/probe/`·`bot.sqlite3` 일괄 rename 필요.
- 절차: 운영 메모 §8 "slug 스키마 마이그" — N100 services 정지 → dev push → N100 pull → `migrate_slug_schema.py --dry-run` → `--yes` → services 재개.
- *N100 에서 migrate 돌리지 X* (룰 B 예외 같지만 — migrate 결과 git 추적 configs/ 도 건드림 → push 안 하면 비대칭).
- 대신: dev box migrate → push → N100 pull. `migrate_slug_schema.py` idempotent → 양쪽 같은 mapping.

## 6. hand-config 워크플로 — 자율 개선 시

자동 등록 실패 사이트 손-config 또는 probe/prompt/schema/엔진 코드 개선 시:
- `.claude/skills/hand-config/SKILL.md` 절차 따름
- 자가 점검 가이드 (SKILL.md §6, 가이드라인, 권장)
- `docs/cases/<slug>.md` 작성 + `python scripts/cases_index.py`
- **`python scripts/cases_index.py --backfill-db output/cases.sqlite3`** — *반드시*. case_runs DB 에 row 박지 않으면 dashboard `/cases` 탭에 *안 보임* (file 만 만들고 빠뜨리면 다음 사람이 못 찾음).
- `Agent(subagent_type='hand-config-reviewer', model='sonnet')` 호출
- pre-push hook 통과 후 push → N100 pull → restart

`output/cases.sqlite3` = git ignored (output/ rule). dev box 만 backfill. N100 dashboard 안 봄.

`docs/자가개선 인프라 계획.md` 전체 설계 (rev 3).

## 7. 안전 동작

### 7a. 절대 금지
- `git push --force` (특히 main)
- `git rebase` on shared branches

### 7b. 확인 후 진행
- N100 `git stash drop` (보존 데이터 손실)
- `git reset --hard` (특히 N100)
- `migrate_slug_schema.py --yes` (mapping 미리 dry-run 검토)
- bot/dashboard restart 도중 (사용자 영향 — 잠시 폴링/대시보드 끊김)
- `--no-verify` (pre-push 우회)

### 7c. 자율 허용
- dev box `git commit && git push`
- `python scripts/probe_smoke.py`·`python scripts/cases_index.py`
- pre-push hook 자동 검증
- `Agent(subagent_type='hand-config-reviewer', model='sonnet')` 호출

## 8. 추천·결정 룰

### 8a. *영구 게이트* 우선 — *이번만 우회* 후순위
사용자에게 옵션 제시할 때 "이번 batch 만 머리로 우회" / "SKILL.md·prompt·코드 안 바꾸고 임시 처리" 식의 *이번만* 안을 **1순위 추천 X**. gap 이 SKILL.md / prompt / engine / probe / docs 의 *영구 박기* 로 봉합 가능하면 그걸 1순위.

**왜**: 같은 패턴 다음에도 옴 — gap 그대로면 다음 사람/세션이 같은 실수 반복. 자가개선 인프라 (CLAUDE.md §6 / ADR 0003) 의 직접 적용.

**언제 *이번만* 안이 정당**: 게이트 박기가 정말 over-engineering 일 때 만 (단일 사이트, 재발 가능성 0, fix 비용 ≫ 영구 박기 비용). 그런 경우 *명시* 후 사용자 동의 받기.

**구체 예**:
- ✅ "SKILL.md §0b preflight 게이트 박고 그걸로 이번 batch 처리" (영구 + 즉시 효과)
- ❌ "이번만 머리로 preflight 적용 — SKILL.md 는 다음에" (이번만 우회. gap 남음)

이 룰 자체가 2026-05-19 사용자 feedback 으로 박힘 — 이전 다수 turn 에서 같은 패턴 반복 관찰.

**범위 = 사이트 등록 gap 뿐 아니라 *오케스트레이션·하네스·process 실수*도 포함** (2026-05-22 사용자 feedback). 자가개선 인프라(§6/ADR 0003)는 등록 품질(probe/prompt/recognizer) 대상이지만, *Claude 가 batch 를 모는 방식*의 실수 — watcher 를 shell `&` 로 띄워 알림 유실, two-dot diff 오진, URL 과도 remap, 남의 파일 stage 등 — 도 같은 룰을 받는다. **그런 실수를 잡으면 "재시도하고 넘어감"으로 끝내지 말고, 그 자리에서 durable layer 에 게이트를 박아라**: SKILL.md(§0c 등)·CLAUDE.md(§9 등)·해당 스크립트 docstring·`feedback-*` memory 중 맞는 곳. 게이트 박기가 한 줄이면 *이번 turn 에 같이* 박는다 (별도 follow-up 으로 미루기 X). "내가 알아챘으면 즉시 영구화" 가 기본 반사. (예: 2026-05-22 shell `&` watcher 유실 → `codex_watch.py` 멀티파일+docstring 경고 + SKILL §0c step 4 + 이 줄.)

## 9. 동시 dev 세션 — 병렬 git etiquette

여러 Claude/codex 세션이 *같은 dev box·같은 로컬 repo·같은 main* 에서 동시 작업 가능 (별도 clone 아님). 흔함 — 한 세션이 batch A, 다른 세션이 batch B. 핵심: **git 상태가 내 것만이 아님**. 2026-05-21 동시 batch 중 오진·혼란으로 박힘.

### 9a. main 이 내 밑에서 advance 한다 (정상)
- 다른 세션이 main 에 커밋 → `git log`/HEAD 가 내가 모르는 커밋 보임. **정상이지 손상 아님**. 내 커밋은 공유 main 에 안전히 누적.
- worktree review diff: `git diff main...branch` (**three-dot** = merge-base 기준 = 내 변경만). ⚠ **two-dot `main..branch` 금지** — 다른 세션이 advance 시킨 커밋을 *내 branch 가 삭제한 것처럼* 가짜 표시 (codex 가 무관 파일 지운 줄 오해). 상세 `docs/codex 위임 가이드.md` §7.
- **merge 는 3-way 안전** — disjoint 변경이면 다른 세션 커밋 보존(삭제 0). 충돌은 공유 파일(INDEX.md 등 양쪽 regen)뿐 → `cases_index.py --backfill-db` 로 해결. 사전 확인 `git merge-tree $(git merge-base main branch) main branch | grep -i conflict`.

### 9b. 내 파일만 stage — 남의 uncommitted 건드리지 X
- `git status` 의 uncommitted/staged 변경이 **다른 세션 것일 수 있음**. `git add -A` / `git add .` / `git commit -am` **금지** — 남의 작업 잡아챈다.
- 항상 **내가 만든·고친 파일만 명시** `git add <path1> <path2>`.
- 남의 uncommitted·staged·worktree 파일 = revert·overwrite·삭제 X. 내 작업과 무관하면 *그대로 둔다* (§7a 의 "내가 안 만든 것 건드리기 전 멈춤" 정신).
- 단일 세션 확실할 때만 `add -A` 편의 허용.

### 9c. push 는 fast-forward, N100 은 마지막 pull 이 다 받음
- 같은 로컬 main → `git push` = origin ff. 다른 세션도 같은 main push (idempotent). N100 pull-only → 어느 세션이 마지막에 pull 하든 양쪽 작업 다 받음.
- git index lock 이 merge/commit 직렬화 — 레이스 시 transient `.git/index.lock` 뜨면 재시도.

> 안 지키면: 다른 세션 작업 유실 / 가짜 삭제 오진 / push 충돌. **worktree 격리(edit) + 내-파일-only staging + three-dot review** 3개면 동시 작업 안전. codex 위임 동시 batch 의 전체 규율 = `docs/codex 위임 가이드.md` §7 + `.claude/skills/hand-config/SKILL.md` §0c.

## 10. 관련 문서

- `docs/운영 메모.md` — N100 SSH·systemd·배포 사이클 §1~9
- `docs/공개 현황 사이트.md` — N100 Tailscale Funnel 공개 정적 사이트 접속·재부팅 복구·끄기 (ADR 0010)
- `docs/자가개선 인프라 계획.md` — hand-config 자가개선 인프라 v3 설계
- `docs/cases/INDEX.md` — 사이트별 등록 시도 사례 (자동 생성)
- `docs/config 기반 엔진 가이드.md` — config 엔진 전체 구조
- `docs/config 자동생성 실패 케이스.md` — 자동 등록 실패 분류
- `docs/사이트 어댑터 추가 가이드.md` — 손-adapter 추가 절차
- `docs/크롤링 지침.md` — 정책 (polite_sleep, robots, 우회 금지)
- `docs/대시보드 가이드.md` — dev 박스 로컬 대시보드
- `docs/디스코드 메시지 톤 가이드.md` — 봇 사용자 향 메시지 톤·문체·포맷 룰 (해요체·이모지 어휘·체크리스트)
- `docs/codex 위임 가이드.md` — 일반 작업을 Codex CLI 로 위임하는 기준·절차 (언제 YES/NO·entry/middle/exit·diff 게이트). batch/hand-config 외 작업용. ADR 0008 의 운영 가이드.
