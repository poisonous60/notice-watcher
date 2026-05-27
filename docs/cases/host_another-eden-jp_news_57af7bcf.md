---
slug: host_another-eden-jp_news_57af7bcf
url: https://another-eden.jp/news/
status: "🧩 수동 config — playwright_html + disable_stealth, JS hydration 116 row"
outcome: handcrafted
fix_layer: none
failure_keys: [posts_nonempty, js_hydrated_list_static_shell, agentic_selector_miss]
date: 2026-05-27
config_strategy: playwright_html
tags: [hand-config, game-mobile, ja, jp]
---

## 진단

- live: `curl -sI https://another-eden.jp/news/` → 200 OK. 정적 HTML shell 5565 bytes, `#backnumber` 비어 있음. JS hydration 후 `#backnumber > li` 116 row 채워짐 (probe stealth render 확인).
- last_feedback: `posts_nonempty: 0건` ×2 (agentic max_cycles failed)
- diagnosis verdict: `정적 HTTP로 충분` (**잘못 판정** — 실제 hydration 필요)
- `cases_index query --failure-key posts_nonempty,js_hydrated_list_static_shell --json` → 누적 hit (이미 batch-2026-05-26-games-mobile 의 valheim case 등에 같은 패턴)

## E/D/C/B/A/F audit (§2 강제 인용 4a)

- E: miss — schema 거부 자리 X (config 형식 정상)
- D: miss — retry feedback 자리 X (LLM 이 selector 자체 못 잡음, feedback 메시지 강화로 해결 X)
- **C: hit candidate** — `probe/diagnose.py` verdict 휴리스틱이 "정적 HTML shell 안 row 비어있는데 JS hydration 후 row 채워짐" 신호 (raw HTML vs Playwright rendered DOM 행 cnt delta) 검출 못 함 → `_generic_probe_verdict_soft404_and_static_rows.md` deferred entry `probe_verdict_promote_render_when_raw_anchor_zero` 와 같은 자리. 누적 3건째 (granbluefantasy, metacoregames, another-eden) → 다음 case 들어오면 lift.
- B: miss — few-shot 추가 도움 X
- A: miss — system 룰 추가 도움 X
- F: miss — recognizer/엔진 코드 변경 X

C-layer deferred entry hit — 본 case 의 fix 는 hand-config (Track A) 로 봉합. C-layer lift 는 후속 (3건째 누적 — `_deferred_heuristics.md` 의 `probe_verdict_promote_render_when_raw_anchor_zero` 항목 trigger 도달).

## Track A 결정 (§2 강제 인용 4b/4c)

- 4a Track B 6-layer: C-hit (deferred) — 단 본 case 에서 lift 안 함 (3건째 누적 도달 — 후속 chunk).
- 4b Track A 진입 조건 (a) 6-layer all miss = 부분 만족 (C 는 deferred, lift 안 함이라 effective miss). (b) ship 명시 = batch hand-config operator default false. 그러나 사용자 첫 메시지 "수동 config 만들라고 triage 큐 hand-config 돌린건데" + "잔여 2건 진행해" = **본 batch 의 명시 ship 승인** (all-residual scope).
- 4c context: operator flow + 사용자 명시 ship evidence "수동 config 만들라고 ... 진행해" → Track A 진입 OK.
- 4d park bucket: N/A (Track A success).

## 수동 config 절차

1. probe artifact `list_candidates.json` 확인 — selector `#backnumber > li` cc=116 명확.
2. direct curl 시 0 row 확인 → SPA hydration 필요 → `strategy=playwright_html` + `wait_selector`.
3. `disable_stealth: true` 박음 (commit `7ee403a` flag) — anti-bot 아님이지만 stealth-DNS race 회피.
4. fields: post_id=YYYYMMDD URL segment, title=`dd a`, published_at=`dt` text regex.
5. article body: `article` selector (text_len 1034).

## 검증

- schema PASS
- smoke fetch_list = 10 rows (baseline), article body = 1874 chars
- local register: baseline 30건 등록 ✓
- probe_smoke (post-merge): exit 0 PASS 1672

## 일반화 후보 (deferred)

`_deferred_heuristics.md` 의 `probe_verdict_promote_render_when_raw_anchor_zero` 항목 — 3건째 누적 도달 (granbluefantasy SvelteKit + metacoregames Next.js+Panda + another-eden 자체 SPA). 다음 1건 들어오면 통합 설계 + lift.
