# ADR 0020 — `config_generate` agentic mode for register

- 상태: Accepted
- 날짜: 2026-05-25
- 관련: ADR 0008 (hand-config 오케스트레이션 → codex CLI), ADR 0015 (worktree-isolation), `output/plan_register_agentic.md` (rev 5), `scripts/experiments/codex_sandbox_probe.py`

## 맥락

register subprocess 의 `config_generate` call_site 가 `output/llm_routing.json` 에서 `codex:gpt-5.4-mini#low` 로 라우팅돼 있다. 하지만 `generate/codex.py` 는 `--ephemeral --cd <tmpdir>` 로 codex CLI 의 agent 능력 (tool use, multi-turn, file ops) 을 모두 죽이고 *1-shot JSON* API 흉내만 시킨다. Python (`generate_config_validated`) 이 4-retry loop 를 돌리는데, 매 retry 가 별도 codex subprocess cold start (≈20 s) 라 worst of both worlds — 속도 = agent, 능력 = API.

핵심 직관: **agent 의 진짜 win 은 *prior-art lookup* 이다**. 막혔을 때 *비슷한 다른 configs*, *recognizer 코드*, *prompt 템플릿* 을 직접 까서 보고 grounded 한 config 를 짤 수 있음. self-retry 는 부수효과.

## 결정

1. **`config_generate` 의 routing 에 mode sidecar (`config_generate__mode = agentic | api_loop`) 추가** — 기본 `api_loop` (기존 동작). `agentic` 일 때만 `generate/codex_agentic.py` 의 multi-turn agent 경로로 분기. provider=gemini + mode=agentic 조합은 dashboard validator + runtime guard 에서 fail-closed.
2. **Agent boundary**: probe → recognize → preflight → digest 는 `register.py` 그대로. agent 의 책임 = digest 받아 `(config: dict, ValidationReport)` 반환. baseline / 마커는 parent 의 기존 흐름.
3. **Trust boundary — tmpdir-only**: agent 는 자기 tmpdir 안만 write. repo 어디든 write 시도 = violation. **parent 는 *오직* tmpdir 의 candidate.json 만 읽어 atomic publish**.
4. **Sandbox 보호 0 가정**: Windows codex CLI 의 `--sandbox workspace-write` 가 PowerShell command 자체를 policy reject — 동작 불가 (실측: `scripts/experiments/codex_sandbox_probe.py`). 따라서 `--dangerously-bypass-approvals-and-sandbox` 로 호출. sandbox 가 protection 안 줌 → **guard 는 prompt + AGENTS.md + 사후 audit 만**.
5. **7-layer guard**: prompt / AGENTS.md / output-schema strict / 180 s wall-clock / process tree kill / SHA256+mtime+size audit / **parent re-validate (trust boundary anchor)**.
6. **Parent re-validate 의무**: agent JSON `ok=true` 는 후보 신호일 뿐. parent 가 `validate_built_config(agent_config_dict)` 를 *재실행* 해서 진짜 ValidationReport 만든 후에만 publish.
7. **Atomic publish**: `tempfile.NamedTemporaryFile(dir=configs/)` + `Path.replace`. agent timeout/kill 시 live config 영향 0. per-slug 동시 register 시 last-writer-wins 지만 torn read 없음.
8. **AUDIT_FAIL → `.BUG.json` + OWNER DM**: system violation (NOT site fault). `register.py` rc=-4 신규. `bot/worker.py` rc=-4 분기 + `dm_owner(...)`. `is_blocked` 가 BUG 도 잡으므로 자동 retry X — 사람-개입 대기.

## 결과

- (+) Agent 가 *prior-art lookup* 가능 → grounded generation. 같은 사이트 패턴 examples 보고 따라 함 → hallucination 줄어듦
- (+) cold start 1번만 (4-retry × 20 s ≈ 80 s → 단일 multi-turn ≈ 60-180 s). validate 통과 시 즉시 종료 가능
- (+) routing.json 한 줄 토글 (`config_generate__mode=agentic`) — N100 자동 반영 (mtime cache)
- (+) 사용자 차단 0 — `api_loop` 가 default. 명시적 opt-in
- (−) Windows sandbox 보호 0 → guard 모두 prompt+AGENTS+audit 에 의존. agent 가 룰 위반 시 detect-after-fact (사람 손-개입 필요)
- (−) chromium_lock 점유 시간 늘어남 (agent thinking 180 s 동안 slot 1개 점유 → pool_size>1 시 다른 register 대기). measurement 단계에서 영향 관측
- (−) audit attribution 한계: pre/post snapshot 사이에 다른 dev 세션이 공유 코드 변경하면 agent 위반과 구분 불가. accepted risk (dev box single-user 가정, N100 single-register Linux flock)
- (−) per-slug lock 의 Windows no-op — dev box 에서 같은 slug 동시 register 두 개면 race. dev 가정으로 봉합. N100 Linux 는 정상 lock

## 기각한 대안

- **`configs/<slug>.json` write 예외 (rev 3)**: agent 가 직접 거기 쓰게 허용 + parent overwrite. codex 4차 review 에서 HIGH — live config/state mismatch race (publish 중간 polling 워커가 반쯤 쓴 JSON 읽음, baseline 어긋남). 폐기 → tmpdir-only.
- **mtime+size audit 만 (rev 2)**: `os.utime()` + 같은 size 우회 가능. SHA256 필수. test_codex_agentic 의 `audit_catches_mtime_spoof_via_sha` 에서 회귀 잠금.
- **agent 가 직접 `generate/codex.py` 의 agentic 모드 풀기**: LLMClient 추상화가 1-shot text-in/out 만 모델. agentic 은 별 file (`codex_agentic.py`) + 별 dispatch path. `client_for()` 우회 — fallback 의미 안 섞임.
- **git diff 기반 revert (rev 1)**: register subprocess 가 git 만짐 = 동시 dev 세션 변경까지 되돌릴 위험 (CLAUDE.md §9b 위반). 폐기 → mtime+SHA snapshot + 자동 revert 안 함, AUDIT_FAIL = alert 만.
- **opencode / 다른 IDE agent**: ChatGPT Plus quota OAuth 동점이나 quota clamp 위험 (Anthropic 의 2026-04 선례). codex CLI 유지 — ADR 0008 과 같은 결정.
- **N100 codex CLI 직접 분리 (Linux sandbox 가 정상 동작 가정)**: dev box (Windows) 와 routing/path 갈리면 SoT 깨짐. 첫 PR 은 단일 path (bypass), N100 measurement 후 Linux 전용 sandbox path 별 PR.

## 미해결 (후속)

- N100 (Linux) codex sandbox 동작 검증 — `workspace-write` 가 진짜 막는지 실측. 동작하면 Linux 전용 sandbox 강화 path 추가.
- multi-turn token usage 의 accurate accounting — 현재 `_sum_usage` 가 turn.completed 만 합. tool-use 의 hidden tokens 누락 가능. codex CLI 의 fine-grained usage event 출시 시 갱신.
- chromium_lock 점유 영향 측정 후 — 길면 agentic 진입 전 lock 풀어주는 path 검토. validate 의 chromium fetch 시 다시 잡음.
- examples 선정 알고리즘 강화 — 현재 4-axis score. 추후 embedding 기반 유사도 가능.

## 검증

- unit: `python tests/llm/test_routing.py` 22 PASS, `python tests/llm/test_codex_agentic.py` 14 PASS
- sandbox 실측: `python scripts/experiments/codex_sandbox_probe.py` — 3 case 결과 (`output/sandbox_probe_summary.json`)
- codex review: 5 round (`output/codex_generic_codex-review-register-agentic-{task,rev2-task,rev3-task,rev4-task,rev5-task}_prompt.result.md`) — GO with caveats (rev 5)
- 실측 measurement (별 PR / 이번 PR 후 dev box 검증): `scripts/experiments/compare_agentic_vs_api_loop.py` (TBD)
