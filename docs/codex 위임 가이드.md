# codex 위임 가이드 — dev 박스에서 일반 작업을 Codex CLI 로 넘기기

dev 박스에서 Claude 가 무거운 작업을 **Codex CLI** 에 넘겨 Claude(Max) quota 를 아끼는 방법.
batch·hand-config 는 전용 경로(아래 §6 참조)가 따로 있고, 이 문서는 **그 외 일반 작업**(버그픽스·리팩터·코드 작성 등)을 같은 하네스로 위임하는 기준·절차다.

> 결정 근거: `docs/adr/0008-handconfig-orchestration-on-codex.md`. codex-측 플레이북 override: `AGENTS.md` §6.
> 이 문서 = **Claude(위임자) 측** "언제·어떻게 넘기나" 운영 가이드.

## 1. 왜 위임하나

무거운 LLM 일을 OpenAI(codex) 로 흘려 Claude quota 를 보존. 100~200 사이트 batch 같은 고볼륨 작업이 Claude quota 를 빠르게 태우던 문제(ADR 0008 맥락)의 일반화. Claude 는 **기획·설계·진입·diff 검토** 에 집중, codex 는 **중간 실행**(읽기·진단·수정·검증) 담당.

## 2. 언제 위임하나 (YES / NO)

위임 여부는 **Claude(entry)** 가 판단. 매번 사용자가 지시하지 않아도 아래 기준으로 결정.

**YES — 다음 셋 다 만족할 때:**
- **검증 가능** — 결과 정오를 기계적으로 판정 가능 (`probe_smoke` / 테스트 / 재현 명령 / `git diff` 로 확인됨). codex 결과는 맹신 안 하고 게이트로 잡으므로 게이트가 있어야 위임 가치.
- **토큰 무거움** — quota 아낄 값어치 있는 분량 (probe artifact 다독·다파일 수정·반복 생성 등).
- **disjoint** — 공유 인덱스(INDEX.md·cases.sqlite3)·git·N100 배포를 codex 가 안 건드림. 그건 Claude 직렬 (§5).

**NO — Claude 가 직접:**
- **설계·아키텍처·grill** — ADR·인터페이스 결정·tradeoff 판단. ADR 0008 §결정 1 "Claude = 기획·설계 전용".
- **검증 불가능한 판단** — diff/테스트로 정오를 못 잡는 것 (애매한 UX 카피, 정책 판단 등).
- **trivial** — 위임 오버헤드(프롬프트 작성·창 띄움·watch·diff 검토) > 작업 자체. 한두 줄 수정은 그냥 Claude.

## 3. 도구 (이미 있음 — `scripts/`)

| 도구 | 역할 |
|---|---|
| `scripts/codex_handoff.py generic --task-file <f> [--launch] [--no-worktree]` | 자유 작업 위임 프롬프트 빌더. HARD-STOP(commit/push/배포 금지, 검토 후 STOP) + probe_smoke·vocab_lint 검증 자동 박음. `--launch` 는 worktree 기본이며, `--no-worktree` 는 사용자가 명시한 단일 기계 작업 예외에만 쓴다. |
| `scripts/codex_handoff.py bugfix --title <t> --repro <cmd> [--location <file:line>] [--launch]` | 버그픽스 전용 — repro 명령·위치 박힌 프롬프트. |
| `scripts/codex_run.ps1` | 보이는 PowerShell 창에서 `codex exec` 실행. 창 = codex 콘솔 직접(live). `-o` 결과파일. rc=0 시 3초 후 자동 닫힘. |
| `scripts/codex_watch.py <result> --loop` | 결과파일 polling 완료 감지 (visible-window 는 harness 추적 X → 별도 신호). DONE/TIMEOUT. |

`--launch` 주면 handoff 가 프롬프트 작성 후 codex_run.ps1 로 바로 창 띄움.

## 4. 절차 (entry=Claude → middle=codex → exit=Claude)

1. **진입 (Claude)** — §2 기준으로 위임 결정. 작업을 명확히 기술한 task 파일 작성:
   ```
   output/codex_task_<name>.txt   ← 작업 내용 (목표·제약·검증법)
   ```
   task 본문에 파일 제한을 박지 않는다. 특히 hand-config/batch 는 필요한 repo 파일을 자유롭게 수정하게 하고, Track B 후보를 사전에 봉쇄하지 않는다.
2. **위임 (Claude)**:
   ```powershell
   python scripts/codex_handoff.py generic --task-file output/codex_task_<name>.txt --launch --worktree
   ```
   보이는 창 뜸. **Claude 토큰 0** — 이후 codex 가 실행. 창 안 자라면 hang(사용자가 눈으로 봄).
3. **완료 감지 (Claude)**:
   ```powershell
   python scripts/codex_watch.py output/codex_generic_<name>_prompt.result.txt --loop
   ```
4. **검토·배포 (Claude)** — codex 는 commit 전 STOP. Claude 가 **직접 산출물 읽고 audit 의무** (headline 수치·result.md 요약만 보고 바로 commit X — §7 "codex 산출물 신뢰 함정"):
   - **4a. scope audit** — `git diff main...<codex-branch>` 로 실제 변경을 읽고, task 목표·Track B 우선순위·HARD-STOP 과 맞는지 검증.
   - **4b. 변경 내용 audit** — 각 변경 파일의 diff 를 *Claude 가 직접 읽는다*. 보는 것:
     - 로직이 task 요구와 맞나 (codex 가 task 오독·우회·시늉만 한 케이스 검출).
     - 새 코드의 명백한 버그·dead path·잘못된 예외 처리·구문 오류 (`probe_smoke` 안 잡는 영역).
      - case body / 산출 문서가 있으면 §회피 게이트 4종 (probe pull skip·일반화 punt·처방-우선 task 추종·`no_change` 정당화 불충분 — 자세히 `feedback-codex-punt-audit` memory) 적용.
     - codex `result.md` 의 "✓ 완료" 주장이 실제 diff 와 일치하는지 cross-check.
   - **4c. 기계 검증** — `probe_smoke --stage 3 --stage 5` PASS 재확인. 변경 영역에 unit test 있으면 그것도.
   - **4d. 통과 시** Claude 가 commit/push → N100 배포 (commit 후 자동 배포 룰). 위반/미흡이면 commit 안 하고 그 자리서 직접 수정 또는 codex 재위임(발견 사실 task 머리에 명시 — 두 번째에 같은 punt 안 하게).

## 5. 공유 자원은 Claude 직렬

codex 가 절대 안 건드림 (병렬·레이스 위험):
- `git add`/`commit`/`push` — Claude 가 검토 통과 파일만 명시(`-A` 금지).
- N100 ssh/systemctl/pull/배포.
- 공유 인덱스: INDEX.md·cases.sqlite3.
- 작업 대상 외 configs/·poll_state/·triage_queue.

HARD-STOP 프롬프트가 이걸 박지만 — **prompt 제약(soft)** 이라 파일시스템 강제 아님. 실질 게이트 = Claude diff 검토(§4.4).

## 6. 전용 경로 (이 문서 대상 아님)

- **hand-config** (자동 등록 실패 큐): `codex_handoff.py handconfig …` + `.claude/skills/hand-config/SKILL.md` 플레이북. ADR 0008.
- **batch** (FAILED 큐 대량): `codex_batch.py {plan|emit|launch}` — 플랫폼/host 비중첩 청크 병렬. ADR 0008 §병렬 위임.

이 둘은 SKILL/ADR 절차를 따른다. 일반 작업만 이 문서.

## 7. 학습된 함정

- **codex 는 명시 제약도 위반 경향** — commit·over-edit·"하지마" 무시 전례(2026-05-21). → HARD-STOP 프롬프트 + **Claude diff-review 게이트 필수**. codex 결과 맹신 X.
- **codex 산출물 신뢰 함정 — headline/result.md 만 보고 commit X** — 반복 패턴: codex 가 STOP 후 result.md 에 "8건 ✓ 완료" 적으면 Claude 가 diff 안 까고 바로 commit/push → 후에 버그·punt·task 오독 발견. `result.md` 는 codex 의 *자기 보고* — 검증 아님. **반드시 §4.4b 처럼 Claude 가 직접 diff 와 변경 파일 본문을 읽고 audit**. 영구 게이트 = §4.4b + `feedback-codex-punt-audit` memory + `.claude/skills/hand-config/SKILL.md` §0c step 5d (hand-config 경로). 일반 작업도 같은 의무 — 이 줄로 박음.
- **여러 codex 세션은 worktree 격리로 띄운다**. 같은 main working tree 공유 실행은 단일 기계적 작업일 때만. batch/hand-config 는 `--worktree` 기본이고 파일 제한 대신 diff review 로 잡는다.
- **PowerShell `Tee-Object`/`2>&1` 금지** — Tee 는 버퍼링+UTF-16 로 live 모니터 깨짐, `2>&1` 은 native stderr 를 ErrorRecord 로 감싸 전부 빨강. 완료는 `-o` 결과파일로만.
- **codex-companion broker(`codex:rescue`) 경로 회피** — Claude in-loop(토큰 목표 위배) + Windows stdout-heavy probe 에서 IPC deadlock(#330). 확정 경로 = codex CLI 직접(codex_run.ps1).
- **worktree 검토 diff 는 three-dot `main...branch` (two-dot 아님)** — 2026-05-21 오진. 병렬 세션이 worktree 생성 *후* main 을 advance 시키면(다른 batch 가 커밋), worktree base 가 main 보다 뒤처짐. 이때 `git diff main..branch` (**two-dot**) 는 *main 이 새로 추가한 커밋들* 을 branch 입장에서 "삭제"로 표시 → codex 가 무관 파일 12개 지운 것처럼 보임(실제론 안 건드림). 올바른 검토 = `git diff main...branch` (**three-dot** = merge-base 기준 = codex 실제 변경만). **merge 는 안전** — `git merge` 는 merge-base 기준 3-way 라 disjoint 변경이면 양쪽 다 보존(삭제 0). 충돌은 공유 파일(INDEX.md 등 양쪽 regen)뿐 → `cases_index.py --backfill-db` 로 재생성 해결. 판정 전 `git merge-tree <base> main branch | grep -i conflict` 로 실제 충돌 파일만 확인.
- **병렬 세션 = 같은 로컬 repo·같은 main 공유** (별도 clone 아님) — 두 Claude/codex 세션이 동시에 *같은* 로컬 main 에 커밋. git index lock 이 merge 를 순차화(레이스 시 transient `.git/index.lock` → 재시도). push 는 같은 local main 의 fast-forward 라 안전. 즉 **worktree 동시 작업은 설계대로 정상** — edit 격리(worktree) + merge 직렬화(index lock) + push ff. 위 two-dot 오진만 피하면 됨.

## 8. 관련

- `docs/adr/0008-handconfig-orchestration-on-codex.md` — driver 결정·위임 하네스·병렬 규율 (SoT).
- `AGENTS.md` §6 — codex CLI 가 매 세션 로드하는 thin override (reviewer 호출 메커니즘 등).
- `.claude/skills/hand-config/SKILL.md` — hand-config 플레이북 (codex 가 junction 으로 로드).
