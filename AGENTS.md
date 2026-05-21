Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

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

## 4. Goal-Driven Execution

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


# AGENTS.md — notice-watcher
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
- **권위 플레이북 = `.claude/skills/hand-config/SKILL.md`** (git-tracked SoT). `.agents/skills/hand-config/` 는 그 junction (같은 파일) — codex auto-discovery 용. 둘이 어긋나면 `.claude/` 가 진본.
- 자가 점검 가이드 (SKILL.md §6, 가이드라인, 권장)
- `docs/cases/<slug>.md` 작성 + `python scripts/cases_index.py`
- **reviewer = native `hand-config-reviewer` subagent** — codex CLI 가 `.codex/agents/hand-config-reviewer.toml` 로 노출, 프롬프트에서 이름으로 위임 호출.
- pre-push hook 통과 후 push → N100 pull → restart

### codex CLI override (이 repo 오케스트레이션 driver = codex CLI)

SKILL.md 를 verbatim 따르되 reviewer 호출만 교체:
- SKILL.md §7a 의 `codex-companion.mjs` Bash 경로 = Claude-orchestration 잔재 (codex→codex nested). **codex CLI 에선 무시**.
- SKILL.md §7b 의 Claude `Agent(subagent_type=..., model='sonnet')` = Claude 전용 도구. **codex 는 호출 불가 — 무시**.
- 1순위 = native `hand-config-reviewer` subagent. fallback 순서: native subagent → (불가 시) §7a codex-companion → (사용자 명시 요청 시만) Claude Agent.

`docs/자가개선 인프라 계획.md` 전체 설계 (rev 3). 본 driver 결정 = `docs/adr/0008-handconfig-orchestration-on-codex.md`.

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
- native `hand-config-reviewer` subagent 호출 (codex CLI — §6 override)

## 8. 관련 문서

- `docs/운영 메모.md` — N100 SSH·systemd·배포 사이클 §1~9
- `docs/자가개선 인프라 계획.md` — hand-config 자가개선 인프라 v3 설계
- `docs/cases/INDEX.md` — 사이트별 등록 시도 사례 (자동 생성)
- `docs/config 기반 엔진 가이드.md` — config 엔진 전체 구조
- `docs/config 자동생성 실패 케이스.md` — 자동 등록 실패 분류
- `docs/사이트 어댑터 추가 가이드.md` — 손-adapter 추가 절차
- `docs/크롤링 지침.md` — 정책 (polite_sleep, robots, 우회 금지)
- `docs/대시보드 가이드.md` — dev 박스 로컬 대시보드
- `docs/디스코드 메시지 톤 가이드.md` — 봇 사용자 향 메시지 톤·문체·포맷 룰 (해요체·이모지 어휘·체크리스트)
