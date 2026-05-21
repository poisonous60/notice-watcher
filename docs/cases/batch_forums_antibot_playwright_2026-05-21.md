---
slug: batch_forums_antibot_playwright_2026-05-21
url: https://www.techpowerup.com/forums/
status: ✅ anti-bot 4 사이트 playwright_html 통과 등록 (Anubis PoW·CF) + simplemachines terminal
outcome: handcrafted
date: 2026-05-21
fix_layer: F
failure_keys: [board_shape_check, gate_reject, capability_blocked]
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [anti-bot, anubis, cloudflare, playwright, capability-blocked, batch-2026-05-21-forums]
---

## 무엇이 일어났나

`infra_antibot_challenge_classify`(80aae69) 가 group A 를 anti-bot 으로 *분류*한 뒤, 후속으로 각
사이트가 **헤드리스 브라우저로 통과 가능한지** 검증 → 4/5 등록.

| slug | anti-bot | 입력 | 등록 URL | row | baseline |
|---|---|---|---|---|---|
| techpowerup | Anubis PoW (XenForo) | /forums/ | /forums/whats-new/posts/ | div.structItem-title | 25 |
| lazarus | Anubis PoW (SMF) | / | index.php?action=recent | div.topic_details | 10 |
| debian | Anubis PoW (phpBB) | / | / (index dd.lastpost) | dd.lastpost | 20 |
| fredmiranda | Cloudflare | /forum/ | /forum/board/41/ | a.topictitle | 30 |
| **simplemachines** | **Cloudflare managed** | /community/ | — | — | **terminal** |

## 핵심 발견

**Anubis PoW 는 헤드리스 브라우저가 통과** — Anubis 는 in-browser JS proof-of-work 라 playwright 가
JS 실행해 자동 해결(techpowerup: "Making sure you're not a bot!" → "TechPowerUp Forums" 81 thread).
httpx 는 차단(probe BLOCKED_BOT, 80aae69 가 정확히 분류)이나 playwright_html 로 풀림.

**Cloudflare 는 갈림**: fredmiranda 의 CF JS 챌린지는 playwright+stealth 통과(FM Forums 렌더). 단
simplemachines 의 **CF managed challenge 는 헤드리스 탐지로 막힘**(playwright+stealth 도 "Just a
moment..." 고정) → **terminal capability_blocked** (헤드리스로 불가, residential proxy/실브라우저
필요 — 범위 밖, 정책상 우회 X).

### 진단 (§2 강제 인용)
1. last_feedback: `board_shape_check 거부` (anti-bot 페이지가 board 형식 아님으로 오거부 — 80aae69 가 rc=5 로 교정)
2. verdict: 80aae69 후 BLOCKED_BOT (anti-bot 정확 분류)
3. §매칭: capability_blocked (anti-bot) — stealth/render 트랙
4. 분기: F (playwright_html config) — render 로 anti-bot 통과
5. 누적: group A 동일 패턴 [[infra_antibot_challenge_classify_2026-05-21]]
6. preflight: 80aae69(signals.py) 후 rc=5 — render 통과 여부 검증이 본 작업

## 무엇을 바꿨나

### configs/ 4개 playwright_html (위 표)
- 전부 `nav_timeout_ms:30000, idle_timeout_ms:14000`. wait_selector 를 **실제 행 링크로 스코프**
  (etoland 교훈 — skeleton/사이드바 조기 매칭 회피). 각 포럼 소프트웨어별 row:
  XenForo=div.structItem-title, SMF=div.topic_details, phpBB=dd.lastpost, fredmiranda=a.topictitle.
- fredmiranda: forum root 는 virtualized 하이브리드 DOM(추출 불안정) → 보드 페이지 `/forum/board/41/`
  의 깔끔한 phpBB `a.topictitle` 사용.
- debian: phpBB index 의 각 보드 최신글(dd.lastpost) = 사이트 전반 최근 활동. title 은 테마상 generic
  ("Last post")이나 post_id(p=) 고유 → 새 글 검출 동작. wait_selector 로 lazy 렌더 안정화(3/3).

## 검증

- 각 config smoke fetch_list 위 표 baseline. debian 3/3, etoland 4/4 재현.
- simplemachines: playwright+stealth 10s 대기 후에도 title "Just a moment..." → 등록 불가 확인.
- `probe_smoke --stage 3 --stage 5` PASS (102 configs validate).

## outcome = handcrafted

알려진 anti-bot(Anubis/CF) 을 render 로 통과시켜 *알려진 포럼 소프트웨어*(XenForo/SMF/phpBB) 를
등록 — 커버리지 확장. simplemachines 는 terminal capability_blocked (헤드리스 한계, 능력 부족).

## 트랙 B / 후속

- **Anubis 통과 = playwright 일반 능력** — Anubis 쓰는 FOSS 포럼 다수, playwright_html 로 풀림 패턴 확립.
- SMF(lazarus·eevblog)·XenForo(techpowerup) recognizer 후보 — cluster 쌓이면 recognizer-extension.
- simplemachines: residential proxy / 실브라우저 trust 필요 — 현 범위 밖 terminal.
- 폴링 비용: Anubis PoW 매 폴 재계산(N100 CPU). 폴 간격 여유로.
