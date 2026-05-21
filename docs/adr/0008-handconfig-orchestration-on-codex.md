# ADR 0008 — hand-config 오케스트레이션을 Codex CLI 로

- 상태: Accepted
- 날짜: 2026-05-21
- 관련: ADR 0003 (자가개선 인프라), `.claude/skills/hand-config/SKILL.md`, `AGENTS.md` §6

## 맥락

100~200 사이트를 batch 로 시험하면 실패 잔여가 hand-config 큐로 떨어진다. hand-config 세션을 Claude Code 로 돌리면 Claude 구독(Max) quota 가 빠르게 소진돼 테스트 속도가 막힌다.

핵심 관찰: hand-config 의 *무거운 LLM 일* — config 4-retry 생성(`generate/codex.py` → `codex exec`, `output/llm_routing.json` 의 `config_generate`/`config_retry` = `codex:gpt-5.4-mini`)과 §7 reviewer — 은 **이미 OpenAI(codex) 로 간다**. Claude 를 태우는 건 *오케스트레이션/진단* 뿐 — probe artifact 읽기, §2 분기 추론, config/코드 작성.

따라서 "hand-config 를 OpenAI 로 옮긴다" = 정확히는 **오케스트레이션을 Codex 로 옮긴다**.

이전 시도(Codex 데스크탑 앱)가 "잘 동작 안 함" 의 root-cause 2가지:
1. **stale 플레이북** — `.agents/skills/hand-config/SKILL.md` (codex 가 native 로드하는 슬롯, gitignored 로컬 사본) 가 251줄 옛 버전이라 Claude `Agent(...)` reviewer 경로를 박고 있었다. git-tracked SoT 인 `.claude/` 버전(464줄)과 235줄 drift.
2. **GUI subagent 한계** — 커스텀 `.codex/agents/*.toml` subagent 가 tool-backed/GUI 세션에서 접근 안 됨(openai/codex#15250). CLI/TUI 에선 동작.

## 결정

1. hand-config **오케스트레이션 driver = codex CLI** (데스크탑 앱·서드파티 하네스 아님). Claude 는 **기획·설계 전용** (grill·ADR·아키텍처 spot-review).
2. per-case **review = native `hand-config-reviewer` subagent** (`.codex/agents/*.toml`, CLI 에서 동작) + pre-push hook. **매 건 Claude 로 되돌리지 않는다** (그러면 quota 절약 목표가 깨짐).
3. **플레이북 SoT = `.claude/skills/hand-config/SKILL.md`** (git-tracked). `AGENTS.md` 는 thin Codex override — 절차 중복 없음. codex 전용 차이는 reviewer 호출 메커니즘 하나뿐(§7a codex-companion·§7b Claude Agent 무시, native subagent 1순위).
4. `.agents/skills/hand-config` 는 `.claude/skills/hand-config` 로 향하는 **directory junction** — codex auto-discovery 유지 + 물리적으로 같은 파일 = drift 영구 0. junction 은 gitignored 로컬 = per-dev-box setup (setup-hooks 후보).

## 결과

- (+) Claude quota 가 hand-config 에서 해방 → 100~200 볼륨 테스트 가능.
- (+) SoT 단일·drift 0 (junction). codex 가 항상 현재 플레이북 로드.
- (−) 한 ChatGPT 구독을 batch(N100) + 오케스트레이션(dev box CLI) + reviewer 셋이 같은 5h 윈도우에서 공유 → 고볼륨 시 OpenAI 쪽 throttle 로 재병목 가능. 완화: batch↔hand-config 시간대 분리, 또는 batch 는 gemini fallback 허용.
- (−) GUI(데스크탑 앱) 포기 — #15250 subagent 한계. CLI/TUI 만.
- (−) junction = 새 dev box 마다 한 번 박아야(gitignored).

## 기각한 대안

- **opencode 로 갈아타기** — ChatGPT 구독 OAuth first-class 지원해 quota 는 동점이나, reviewer 재포팅 + 도구 2개 운영 + 서드파티 sub-auth clamp 위험(Anthropic 이 2026-04-04 Claude 구독을 서드파티 하네스에서 차단한 선례). 통합 비용·안정성에서 Codex 가 우위. 측정된 plan B 로 보류.
- **Codex 데스크탑 앱** — GUI 세션 #15250 으로 native subagent 접근 불가.
- **Claude → `codex:rescue`(codex-companion 1.0.4 broker)** — Claude in-loop(토큰 0 목표 위배) + broker 가 Windows 에서 stdout-heavy PowerShell(우리 probe)에 IPC pipe deadlock → `state=running` 무한대기(codex-plugin-cc#330). 2026-05-21 df-nexon run 8분 hang 의 root-cause. 진행 가시성도 placeholder 이름(#321)으로 깨짐. **확정 경로 = codex CLI 직접**(`codex exec ... - < promptfile` + `--dangerously-bypass-approvals-and-sandbox`): Claude 토큰 0, 터미널 라이브 스트리밍, broker 우회로 #330 비해당.
- **매 hand-config 를 Claude 로 재검토** — 품질↑이나 quota 절약 목표와 정면 충돌.
- **AGENTS.md 에 전체 절차 복제** — 독립적이나 SKILL.md 와 drift 원천.

## 위임 하네스 (2026-05-21 구현)

검증 세션에서 ad-hoc 으로 하던 codex 위임을 재사용 가능한 도구로 박았다 (dev-box 전용, N100 런타임 무관).

- `scripts/codex_run.ps1` — codex exec 를 *보이는* PowerShell 창에서 실행. 창 = codex 콘솔 직접(live view, native 색). `-o` 결과파일(UTF-8 최종응답). rc=0 시 자동 닫힘(3초 후), 실패 시 창 유지.
- `scripts/codex_watch.py` — 결과파일 polling 완료 감지 (visible-window 는 harness 추적 X 라 별도 신호 필요). `--loop` 으로 DONE/TIMEOUT.
- `scripts/codex_handoff.py` — HARD-STOP(commit/push/배포 금지, STOP for review) 박은 위임 프롬프트 빌더. `handconfig`/`bugfix`/`generic` + `--launch`.
- `scripts/codex_batch.py` — FAILED 큐를 *겹침 없는* 플랫폼/host 청크로 분할(slug별 X — 같은 플랫폼 recognizer/engine fix 충돌 회피) → 청크별 codex 병렬. 공유 인덱스(INDEX.md·cases.sqlite3·git)는 Claude 직렬.

**프로토콜 (entry=Claude, middle=codex, exit=Claude)**:
1. 진입 = 평소대로 (dashboard/triage 복사 프롬프트 → Claude). Claude 가 §0b preflight·entry.
2. 중간 orchestration(probe 읽기·진단·fix·probe_smoke) = codex, 보이는 창. **Claude 토큰 0**.
3. codex 는 commit 전 STOP (HARD-STOP 강제). Claude 가 git diff 검토 → commit/push/N100 배포.
4. batch = Claude 가 청크 분할(codex_batch) → N codex 병렬(각 느림, 독립, 토큰 0 이라 throughput 은 병렬로) → 결과 수집 → 직렬 commit·배포.

**학습된 함정 (하네스가 봉합)**:
- PowerShell `Tee-Object` 는 파이프 종료까지 버퍼링 + UTF-16 → live 파일 모니터 불가. → Tee 안 씀, 창=codex 콘솔 직접, 완료는 `-o` 결과파일로.
- `2>&1` 머지 = PowerShell 이 native stderr 를 ErrorRecord 로 감싸 전부 빨강. → 안 함 (stderr 는 창에 native).
- codex 는 명시 제약도 위반 경향(commit·over-edit·내 "하지마" 무시 사례 2026-05-21) → HARD-STOP 프롬프트 + **Claude diff 검토 게이트 필수** (codex 결과 맹신 X).
- visible-window codex 는 hang 시 *사용자가 창으로* 본다 (창 안 자람 = 멈춤). 완료/타임아웃만 codex_watch.

## 병렬 위임 — disjoint 파일 소유 + diff-review 게이트 (2026-05-21-fedi 검증)

`2026-05-21-fedi` batch(100 URL, 6 codex 청크)에서 병렬 위임을 검증했다. **여러 codex 세션을 동시에 띄워 throughput 을 올린다** — 단 안전은 다음 규율로 확보.

**현실 (codex_run.ps1 `Set-Location $repo`)**: 모든 codex 세션이 **같은 working tree 공유**(격리 X). 따라서 두 세션이 *같은 파일* 을 동시 편집하면 디스크 레이스(마지막-쓰기-승, 유실). 이걸 막는 게 핵심.

**규율 (Claude 가 entry 에서 강제)**:
1. **disjoint 파일 소유 사전 배정** — Claude 가 청크별로 *편집할 파일 집합* 을 미리 정하고, 각 codex 프롬프트에 **ALLOW-LIST 제약**("이 파일만 편집, 나머지 금지")을 박는다. `output/codex_file_claims.json` 에 기록(추적·감사용).
2. **충돌 표면 = 공유 파일 2개** — `scripts/register.py`(detect dispatch if-chain) + `probe/extract.py`(detect_* 함수). 새 플랫폼 detect-build 는 둘 다 건드림. **path-match recognizer**(예: StackExchange `/questions`, reddit `/r/`)는 PATTERNS 만 = 공유 파일 0 = **병렬 안전**. **probe-detect 플랫폼**(lemmy/peertube/mbin 등 root-URL)은 두 공유 파일 편집 = **한 청크만 소유 → 나머지 직렬**.
3. **diff-review = 진짜 게이트** — ALLOW-LIST 는 *prompt 제약(soft)*, 파일시스템 강제 아님. codex 가 위반(명시 제약 무시 전례)하거나 예측이 틀리면 **Claude 가 commit 전 `git diff` 로 파일셋 검증** + 청크별 코히어런스 확인. 이게 실질 enforcement(사후지만 git 으로 회수 가능).
4. **escape hatch** — codex 가 ALLOW-LIST 밖 파일이 *필요하다* 판단하면 **STOP + result 에 보고**(몰래 편집·데드락 대기 X). Claude 가 중재(직접 wiring / 소유 청크 commit 후 재배정).
5. **auto-discovery semantic 충돌** — disjoint *파일* 이어도 새 recognizer 파일이 `recognize()` 전역 레지스트리에 영향 → 다른 플랫폼 URL 가로채 기존 테스트 깰 수 있음(fedi 에서 mbin PATTERN 이 XenForo `/threads` 가로챔). PATTERNS 를 **보수적**(고유 경로만)으로 + `probe_smoke --stage 5` 로 검출.
6. **공유 인덱스는 Claude 직렬** — INDEX.md·cases.sqlite3·git commit/push/배포는 병렬 codex 가 건드리면 레이스 → Claude 가 청크 수집 후 직렬 처리(`git add` 는 청크 파일만 명시, `-A` 금지).

**진행 모델**: 첫 batch 는 *관측-우선*(1-2 청크 띄워 codex 품질 확인) → 신뢰되면 *file-isolated 청크 다발 병렬*. fedi 검증 후 다음 batch 부터 **병렬이 기본**(SKILL §0c).

**무제한 병렬의 정답 = worktree 격리** — ✅ **구현됨** (commit 7c5a7f2, ↓ 미해결 절 참조): `codex_run.ps1 -Worktree` 가 codex 세션마다 분리 worktree+branch 생성 → edit 물리 격리 → 공유 파일 직렬화 불요, same-tree race 0. Claude 가 branch review 후 merge. **다음 batch·다중 세션 동시 작업 시 `--worktree` 가 기본**. (detect-dispatch auto-discovery refactor 는 별개 — 미구현.)

**속도 노브** (commit 66806cf): `codex_handoff.py --profile light`(gpt-5.4-mini+low) / `--reasoning low|minimal`. **default = gpt-5.5 medium 유지** — hand-config/batch 위임은 품질 위해 gpt-5.5 medium 그대로(2026-05-21 사용자 결정). 속도 노브는 *순수 기계적 청크*(템플릿 복제)에만 opt-in.

## 미해결 (후속 검증)

- N100 에 `codex login` 됐는지 — 안 되면 batch config-gen 이 routing=codex 라도 FallbackClient 로 gemini 행 (`generate/routing.py:128`). batch 도 OpenAI 로 굳히려면 확인.
- ✅ end-to-end 검증 완료 (2026-05-21): `community.cloudflare.com`(Discourse, gen_fail) 을 codex CLI 직접으로 end-to-end 처리 → commit 4479f22 배포. 190k 토큰 전부 OpenAI(Claude orch 0). 위임 하네스(↑)로 codify.
- ✅ 병렬 위임 검증 완료 (2026-05-21-fedi): 6 청크 병렬/직렬, same-file race 0(disjoint 배정), diff-review 게이트로 enforcement. ↑ "병렬 위임" 절로 codify.
- batch 청크 동시 실행 cap(`codex_batch.py --max`)은 현재 안내용 — 실제 cap(작업 큐) 미구현. 고볼륨 시 OpenAI throttle 관측 후 결정.
- ✅ worktree 격리 구현 (2026-05-21, commit 7c5a7f2): `codex_run.ps1 -Worktree` / `codex_handoff.py --worktree` — codex 가 HEAD 분리 worktree+branch(`codex-wt/<tag>-<stamp>`)에서 실행, edit 물리 격리, rc=0 시 변경을 branch 에 transport-commit. Claude 가 `git diff main..codex-wt/<b>` review → `git merge --no-ff` → `git worktree remove`. **다중 세션(다른 창 codex/Claude 동시)일 때 필수** — 같은-트리 충돌로 파일 유실 관측(fedi 후속 triage). 단 *top-level 세션* 자체 격리는 각 세션이 별도 worktree 에서 띄워야(수동 `git worktree add`); `--worktree` 는 *위임 codex* 격리.
- detect-dispatch auto-discovery refactor — register.py if-chain → discovered platform loop. 미구현(직렬화 병목 시).
