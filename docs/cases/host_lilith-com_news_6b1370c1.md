---
slug: host_lilith-com_news_6b1370c1
url: https://www.lilith.com/news/
status: "✅ handcrafted: agentic playwright_html + news_pc selector"
outcome: handcrafted
fix_layer: none
failure_keys:
  - agentic_max_cycles
  - posts_nonempty_zero
  - mobile_vs_pc_selector_mismatch
config_strategy: playwright_html
requested_by: user (batch ship request, 2026-05-24-games-mobile-strategy-rpg)
date: 2026-05-27
adapters_changed: []
engine_files_touched: []
tags: [manual-config, lilith, agentic-auto-success, locale-zh-cn]
---

## 요약

batch `2026-05-24-games-mobile-strategy-rpg` 의 gen_fail (rc=1) — N100 첫 시도: `[{"i": 1, "validate_ok": false, "error": "0 posts from row selector"}, {"i": 2, "validate_ok": false, "error": "0 posts after selector broaden"}]` (agentic max_cycles 4회). dev box 재시도 1회 (현재 코드, full probe) 시 agentic 이 `playwright_html` + `news_pc` selector + `?locale=zh_CN` URL 로 자동 풀어냄. 사용자 ship 요청 (batch operator).

## live + probe

- live: HEAD 200 OK. 정적 GET 본문 = lilith.com 게임사 뉴스 인덱스 (莉莉丝游戏), html_repeating_patterns `div.news_list.news_pc > a cc=10` (desktop) + `div.news_list.news_mobile > a cc=10` (mobile). 첫 글 `https://www.lilith.com/news/ca56fa83db26fc2d23719b4414bcdad7/?locale=zh_CN`.
- probe verdict: 정적 HTTP 충분
- dev re-run: agentic 이 playwright_html + `wait_selector: div.news_list.news_pc > a` 로 풀어냄 (이전 N100 시도는 mobile selector 만 잡아 desktop UA 와 mismatch → 0건).

## Track B 6-layer audit (ship 진입 전)

- E (schema 거부): miss — schema 통과
- D (retry feedback): miss — feedback "0 posts from row" 명확, 추가 정보 X
- C (probe digest 신호): miss — probe 가 news_pc + news_mobile 둘 다 추출함 (`html_repeating_patterns` 에 표면)
- B (few-shot): miss — site 별 idiosyncratic
- A (system 룰): miss — desktop UA 시 _pc variant 우선 룰은 전역 영향 위험 (false-positive)
- F (새 엔진 코드): miss — 새 strategy 불요

cross-site 일반화 0 — lilith.com 만의 mobile/PC variant selector mismatch. agentic 이 그 자체로 풀어냈으니 *추가 generic improvement 자리 없음*.

## ship evidence

- batch operator origin (`2026-05-24-games-mobile-strategy-rpg` catalog) + 사용자 명시 요청: "gen_fail 중… 나머지 하나는 (https://www.lilith.com/news/) 되야 할 것 같아" (turn 2 user message)
- slug/URL 직결 verbatim 인용 ✓ → Track A 진입 (4b a+b 모두 충족)

## 검증

- dev box `register.py "https://www.lilith.com/news/"` 성공 — playwright_html + news_pc selector + 10 baseline
- smoke `make_adapter` fetch_list = 10 posts, body chars 3292
- N100 deploy 후 `scripts/poll.py` 가 자동 picks up

## park 분기

해당 없음 (ship 진입 성공).

## 후속 — vocab_candidates

없음. agentic auto-success 라 어휘 한계 신호 X.
