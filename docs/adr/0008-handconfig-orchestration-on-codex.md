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

## 미해결 (후속 검증)

- N100 에 `codex login` 됐는지 — 안 되면 batch config-gen 이 routing=codex 라도 FallbackClient 로 gemini 행 (`generate/routing.py:128`). batch 도 OpenAI 로 굳히려면 확인.
- 실패 사이트 1개를 실제 codex CLI/TUI 로 end-to-end (§0b→§5) 돌려 native subagent 점화 + push/N100 배포 검증.
