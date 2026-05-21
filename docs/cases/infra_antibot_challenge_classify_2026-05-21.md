---
slug: infra_antibot_challenge_classify_2026-05-21
url: https://forums.debian.net/
status: ✅ probe 분류 게이트 — JS-챌린지 인터스티셜(Anubis PoW / Cloudflare)을 BLOCKED_BOT 으로 인식 → gate_reject(rc=3) 오분류를 capability_blocked(rc=5)로 교정
outcome: improved
date: 2026-05-21
fix_layer: C
failure_keys: [board_shape_check, gate_reject]
config_strategy: none
adapters_changed: []
engine_files_touched: [probe/signals.py]
tags: [anti-bot, anubis, cloudflare, challenge-page, classify, capability-blocked, batch-2026-05-21-forums]
---

## 무엇이 일어났나

`2026-05-21-forums` gate_reject 그룹 A 6사이트(`html_same_host=0`) 중 4개를 stealth 진단 대신
*실제 캡쳐된 list.html* 로 정체 규명 — **전부 anti-bot 챌린지 인터스티셜** (genuine index 아님):

| 사이트 | 인프라 | 캡쳐 title | bytes |
|---|---|---|---|
| forums.debian.net | Anubis PoW (경량 redirect) | `Loading...` | 1233 |
| forum.lazarus.freepascal.org | Anubis PoW (within.website) | `Making sure you're not a bot!` | 4419 |
| www.techpowerup.com/forums | Anubis PoW | `Making sure you're not a bot!` | 4031 |
| www.simplemachines.org/community | Cloudflare | `잠시만 기다리십시오…` | 31358 |
(linuxmint·xenforo.com 은 N100 큐에 없음 — xenforo.com 은 [[project-forums-batch-2026-05-21]] 의 community 서브패스로 별도 해결)

probe 가 이들을 `status 200 OK`(verdict=정적충분, blocked/anti_bot=None)로 분류 → `_policy_check`
통과 → `_board_shape_check` 가 "반복 글 링크 0건" 으로 **gate_reject(rc=3, REJECTED.json)**.
하지만 이건 *능력 부족(anti-bot)* 이지 board 형식 문제가 아님 → **rc=5 capability_blocked 가 정답**.

### 진단 (§2 진입 강제 인용)

1. last_feedback `[FAIL]`: `board_shape_check 거부 (게시판 형식 아님)` (4사이트 공통)
2. diagnosis verdict: `정적 HTTP로 충분`, blocked=None, anti_bot=None (← *오판*. 챌린지 페이지를 정상 200 으로 봄)
3. 실패케이스 §매칭: 신규 — anti-bot 챌린지가 board_shape 로 새는 분류 gap (probe signals 카테고리)
4. 분기: **2c / fix_layer C (probe signals)** — 페이지에 박힌 fact(인프라 챌린지 마커)인데 휴리스틱이 안 잡음. board/비board *판정* 아님(분류기 영역) — anti-bot *차단* 검출이라 probe signals 자리.
5. 누적 cross-check: gate_reject group 의 html_same_host=0 패턴 — [[project-forums-batch-2026-05-21]] 에서 anti-bot 의심 명시됨. 같은 batch 반복.
6. preflight: 해당 없음 (N100 REJECTED.json 진단 — dev box 재현으로 규명).

## 근본 원인 (왜 안 잡혔나 — 두 gap)

`probe/signals.py:classify` 의 봇 마커는:
1. **Cloudflare 전용** (`Just a moment`/`cf-chl-opt`/`challenge-platform`) — Anubis PoW("Making sure
   you're not a bot!", within.website)는 마커 셋에 *없었음*. → debian/lazarus/techpowerup 누락.
2. **강한 마커를 `_strip_scripts` 후 visible_text 로만 검사** — Cloudflare 챌린지 마커
   (`cdn-cgi/challenge-platform`/`__cf_chl`)는 `<script>` 안에 박혀 있어 *지워진 뒤* 검사 → 못 봄.
   → simplemachines 누락.

## 무엇을 바꿨나 (단일 게이트, fix_layer C)

### `probe/signals.py`
- `_BOT_CHALLENGE_MARKERS_RAW` 신규 — JS-챌린지 인프라 고유 문자열 7종 (Anubis: `anubis_challenge`,
  `anubis/api/make_challenge`, `.within.website/x/xess`, `making sure you're not a bot`; Cloudflare:
  `cf-chl-opt`, `cdn-cgi/challenge-platform`, `__cf_chl`).
- `classify` 의 BLOCKED_BOT 섹션에서 *raw body*(스크립트 미제거) `body_text[:50000]` 에 대해 검사 —
  status 200 위장 + 본문 길이 무관하게 매칭 시 `BLOCKED_BOT`. 정상 서빙된 콘텐츠엔 이 인프라 문자열이
  안 나옴(false-positive ~0).

### 자동 재라우팅 (코드 변경 X)
- BLOCKED_BOT → entry_matrix 에 OK list 없음 → `register.py:_policy_check` False (anti-bot 메시지) →
  verdict 가 login/url_dead 아니므로 **rc=5 capability_blocked + FAILED.json**. 기존 라우팅 그대로 탐.

## 검증

- 단위: `tests/probe_heuristics/test_signals_classify.py` +4 케이스 (anubis_full/anubis_redirect/
  cloudflare → BLOCKED_BOT, 정상 포럼 → OK). 4사이트 실제 캡쳐 마커 셋으로 검증.
- **end-to-end**: dev box `register.py "https://forums.debian.net/"` 재probe → `rc=5`,
  `host_forums-debian-n_root_26f67622.FAILED.json` 생성 (이전 REJECTED.json rc=3 → 교정 확인).
- `probe_smoke.py --stage 3 --stage 5` PASS (94 configs 무회귀, stage 5 +4 케이스, coverage 30/30).

## outcome = improved

generic 거부-분류 추론의 개선 — *특정 사이트 adapter 없이* "anti-bot 챌린지를 board 형식 문제로
오분류" 하던 gap 봉합. Anubis/Cloudflare 챌린지를 쓰는 모든 사이트(FOSS 포럼 다수가 Anubis 채택 중)에
적용. fix_layer C + 거부 분류 개선 = improved (CONTEXT.md outcome 표). 챌린지 *유형* 을 더 정확히 분류.

## 사이트 등록 여부 (이 PR scope)

4사이트 모두 **capability_blocked (rc=5, 능력 부족)** 로 정정 — 등록은 *안 됨* (anti-bot 차단,
정책상 우회 X). stealth/storage_state 어댑터(Anubis PoW 풀이 / CF 우회)는 별개 *능력 확장* 작업
([[feedback-batch-fail-priority]]: capability_blocked 는 후순위 stealth). 이 PR 의 목표는 *분류 정정*
(잘못된 gate_reject → 올바른 capability_blocked) 으로, dashboard/triage 가 이들을 "오탐 의심 board
거부" 가 아니라 "능력 부족 anti-bot" 으로 정확히 표기하게 함.

## 트랙 B 검토

이 변경 자체가 트랙 B (anti-bot 챌린지 오분류 재발 차단, 영구 게이트). 추가 일반화 불필요.
