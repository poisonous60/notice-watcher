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
| `scripts/codex_handoff.py generic --task-file <f> [--launch]` | 자유 작업 위임 프롬프트 빌더. HARD-STOP(commit/push/배포 금지, 검토 후 STOP) + probe_smoke·vocab_lint 검증 자동 박음. |
| `scripts/codex_handoff.py bugfix --title <t> --repro <cmd> [--location <file:line>] [--launch]` | 버그픽스 전용 — repro 명령·위치 박힌 프롬프트. |
| `scripts/codex_run.ps1` | 보이는 PowerShell 창에서 `codex exec` 실행. 창 = codex 콘솔 직접(live). `-o` 결과파일. rc=0 시 3초 후 자동 닫힘. |
| `scripts/codex_watch.py <result> --loop` | 결과파일 polling 완료 감지 (visible-window 는 harness 추적 X → 별도 신호). DONE/TIMEOUT. |

`--launch` 주면 handoff 가 프롬프트 작성 후 codex_run.ps1 로 바로 창 띄움.

## 4. 절차 (entry=Claude → middle=codex → exit=Claude)

1. **진입 (Claude)** — §2 기준으로 위임 결정. 작업을 명확히 기술한 task 파일 작성:
   ```
   output/codex_task_<name>.txt   ← 작업 내용 (목표·제약·건드릴 파일·검증법)
   ```
   task 본문에 **편집 허용 파일**을 명시 (ALLOW-LIST). 모호하면 codex 가 넓게 건드림.
2. **위임 (Claude)**:
   ```powershell
   python scripts/codex_handoff.py generic --task-file output/codex_task_<name>.txt --launch
   ```
   보이는 창 뜸. **Claude 토큰 0** — 이후 codex 가 실행. 창 안 자라면 hang(사용자가 눈으로 봄).
3. **완료 감지 (Claude)**:
   ```powershell
   python scripts/codex_watch.py output/codex_generic_<name>_prompt.result.txt --loop
   ```
4. **검토·배포 (Claude)** — codex 는 commit 전 STOP. Claude 가:
   - `git diff` 로 **파일셋 = ALLOW-LIST 인지 검증** (codex 명시 제약 위반 전례 — §7 함정).
   - 변경 코히어런스 확인 + `probe_smoke --stage 3 --stage 5` PASS 재확인.
   - 통과 시 Claude 가 commit/push → N100 배포 (commit 후 자동 배포 룰).

## 5. 공유 자원은 Claude 직렬

codex 가 절대 안 건드림 (병렬·레이스 위험):
- `git add`/`commit`/`push` — Claude 가 청크 파일만 명시(`-A` 금지).
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
- **여러 codex 세션 = 같은 working tree 공유** (codex_run.ps1 `Set-Location $repo`, 격리 X). 같은 파일 동시 편집 = 디스크 레이스. 일반 작업은 보통 1 세션이라 무관하나, 동시 띄우면 disjoint 파일 배정(ADR 0008 §병렬 위임 규율).
- **PowerShell `Tee-Object`/`2>&1` 금지** — Tee 는 버퍼링+UTF-16 로 live 모니터 깨짐, `2>&1` 은 native stderr 를 ErrorRecord 로 감싸 전부 빨강. 완료는 `-o` 결과파일로만.
- **codex-companion broker(`codex:rescue`) 경로 회피** — Claude in-loop(토큰 목표 위배) + Windows stdout-heavy probe 에서 IPC deadlock(#330). 확정 경로 = codex CLI 직접(codex_run.ps1).

## 8. 관련

- `docs/adr/0008-handconfig-orchestration-on-codex.md` — driver 결정·위임 하네스·병렬 규율 (SoT).
- `AGENTS.md` §6 — codex CLI 가 매 세션 로드하는 thin override (reviewer 호출 메커니즘 등).
- `.claude/skills/hand-config/SKILL.md` — hand-config 플레이북 (codex 가 junction 으로 로드).
