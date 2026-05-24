# ADR 0015 — 동시 세션 격리 = git worktree (1차 방어선)

- 상태: Accepted
- 날짜: 2026-05-24
- 관련: ADR 0008 (hand-config 오케스트레이션 = codex), `CLAUDE.md` §9, `scripts/session_start.{sh,ps1}`, `scripts/codex_handoff.py --worktree`

## 맥락

여러 Claude/codex 세션이 같은 dev box·같은 로컬 repo·같은 main 위에서 동시 작업하는 일이 흔하다 (한 세션이 batch A, 다른 세션이 batch B / hand-config + dashboard 동시 / Claude + codex 위임 다발). 공유 working tree 는 구조적으로 다음 사고를 만든다:

- **`git add -A`/`git commit -am` 으로 남의 staged·modified 파일 잡아채기** (2026-05-24 govedu batch — 다른 세션이 내 W2A 16 staged 파일을 자기 LLM-라벨 fix 9 파일과 한 commit `378bccf` 으로 묶음).
- **두 세션이 같은 파일 동시 편집 → 디스크 race** (2026-05-21 codex 다중 세션 fedi batch).
- **`git status` 가 남의 변경 보임 → 내 변경인 줄 오해**.
- **`git merge` 시 남의 uncommitted 변경 때문에 차단** (working tree dirty).

CLAUDE.md §9b 가 "내가 만든·고친 파일만 명시 stage" 룰을 박았지만 *prophylactic 문서 룰*. 자율 세션이 한 번 안 보면 그만 — 2026-05-24 사고가 정확히 그 시나리오.

업계 합의 (2026 검색 — Augment Code, MindStudio, multi-agent-coordination-framework, Zylos 등 다수): **multi-agent 격리 = git worktree** 가 표준. Claude Code 자체도 `isolation: worktree` frontmatter 를 subagent native 지원. 우리는 이미 `scripts/codex_handoff.py --worktree` 로 codex 위임에 박았지만 Claude 본인 세션은 main 직접 — 이번 사고 근원.

## 결정

1. **동시 세션 가능성 = worktree 의무**. 다른 Claude/codex 세션 동시 운영 가능성이 1% 라도 있으면 본인 세션도 worktree 진입.
2. **1인 모드 예외 = 사용자 명시 선언**. "혼자다, main 직접 편집" 사용자가 명시한 경우만 main 직접. 묵시적/추정 X.
3. **표준 진입 = `scripts/session_start.{sh,ps1} <tag>`** wrapper. `git worktree add ../nw-session-<tag> -b session-<tag>` + 출력 = 다음 cd 경로. 일관 디렉토리 (`../nw-session-*`) + branch 네이밍 (`session-<tag>`).
4. **종료 = merge 또는 drop**. 작업 끝나면 main 에 `git merge --no-ff session-<tag>` (CLAUDE.md §9a 3-way 안전) 또는 미커밋 변경은 `git worktree remove + branch -D` 폐기.
5. **scope decomposition 동반 필수**. worktree 가 *파일* 충돌은 막아도 *task* 충돌은 못 막음 — 같은 task 2 agent 에게 주면 둘 다 worktree 안에서 같은 파일 수정 → merge 충돌. SKILL.md §0c "disjoint 파일 소유" 룰을 worktree 사용 여부와 무관하게 유지.

## 결과

- (+) 다른 세션과 file·index race 0 (구조적 — 문서 룰 의존 X).
- (+) `git status` 가 본인 변경만 보여 인지부담 감소 — `git add -A` 류 편의도 안전.
- (+) 머지 = 명시적 단계 → review·conflict 검사 자연 강제.
- (+) Claude Code native `isolation: worktree` 와 동형 — 향후 subagent 자동 호출 시에도 같은 패턴.
- (−) 디스크 ~1-2GB per worktree (shared object store 라 full clone 아님 — 실제 working tree 만큼).
- (−) 머지 한 단계 추가 — 일회성 1-line fix 도 worktree → merge. 1인 모드 예외가 이 비용 면제.
- (−) wrapper 우회 가능 (사용자가 `git worktree` 직접 호출) — 표준 경로만 강제하는 게 아니라 디렉토리·브랜치 네이밍 일관성 잃음. 허용 (전문가 손).

## 대안 검토

| 대안 | 평가 | 채택 X 이유 |
|---|---|---|
| pre-commit hook 으로 `add -A`/`-am` 감지 + 차단 | bandaid | 정당한 broad-add 도 막힘, 우회 가능, *원인* (공유 트리) 미해결 |
| CLAUDE.md §9b 격상 + 시작 시 sentinel 캡쳐 | bandaid | 세션이 안 보면 그만 — 이번 사고가 정확히 그 사례 |
| worktree 의무 + 1인 모드 예외 (본 ADR) | ✅ | 업계 표준, 구조적 격리, 1인 모드 비용 면제 |
| worktree 항상 의무 (예외 X) | over-engineering | 단발 typo 수정도 worktree → merge = 비용 ≫ 가치 |

## 운영

- **신규 세션 진입**: `bash scripts/session_start.sh <tag>` 또는 `pwsh scripts/session_start.ps1 <tag>` — 디렉토리·브랜치 인쇄. cd 후 작업.
- **codex 위임은 이미 자동**: `scripts/codex_handoff.py --worktree` 옵션 그대로 사용 — 변경 X.
- **1인 모드 선언 예시**: "다른 세션 없음, main 직접 편집" 사용자가 message 에서 명시. Claude/codex 가 추정 X.
- **종료 merge**: 사전 충돌 확인 `git merge-tree $(git merge-base main session-<tag>) main session-<tag> | grep -E "^(<<<<<<|>>>>>>)|^CONFLICT"` (§9a — 단어 "conflict" 본문 false positive 피함). 충돌 0 → `git merge --no-ff session-<tag>`. **merge 직전 main working tree 도 clean** 해야 함 (같은 파일 dirty 면 "would be overwritten" 차단 — 내 변경이면 commit/stash, 남이면 §9b 두기).
- **종료 drop**: 미커밋 변경 폐기 시 `git worktree remove ../nw-session-<tag>; git branch -D session-<tag>`.

## 업계 precedent

- [Claude Code native `isolation: worktree` (subagent frontmatter)](https://docs.anthropic.com/en/docs/claude-code)
- [Augment Code — How to Run a Multi-Agent Coding Workspace 2026](https://www.augmentcode.com/guides/how-to-run-a-multi-agent-coding-workspace)
- [MindStudio — Git Worktrees for Parallel AI Coding Agents](https://www.mindstudio.ai/blog/git-worktrees-parallel-ai-coding-agents)
- [multi-agent-coordination-framework / WORKTREE_ISOLATION_PROTOCOL](https://github.com/timothyjrainwater-lab/multi-agent-coordination-framework/blob/main/patterns/WORKTREE_ISOLATION_PROTOCOL.md)
- [Zylos Research — Git Worktree Isolation Patterns for Parallel AI Agent Development (2026-02)](https://zylos.ai/research/2026-02-22-git-worktree-parallel-ai-development)
