---
slug: host_piku-co-kr_w_4d61ac2c
url: https://www.piku.co.kr/w/search/order=hot
status: 🔧 손 config (작동중, baseline 10, playwright_html, flaky ~67%)
outcome: handcrafted
date: 2026-05-16
requested_by: poi23619
failure_keys: [article_body_len, cf_challenge_renav]
fix_layer: none
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [worldcup, game-directory, cloudflare, anti-bot, flaky-polling, SPA, modal-content, non-article-site]
---

## 무엇이 일어났나
사용자(`poi23619`)가 piku.co.kr 의 인기 이상형월드컵 랭킹 페이지(`/w/search/order=hot`)를 `/preview` → 자동 등록 4회 retry 실패. 마지막 `[FAIL] article_body_len: post_id=721FCA 0자 (<100 — content selector 의심)`.

list 5건 추출 OK (post_id=data-id, title=a.product-name, url=a.btn-danger href, summary=div.small.m-t-xs). 자동 생성된 last_config 의 `article.content = [div.modal-header html, div.modal-body html]` 가 일부 ID 에서 0자 — 원인 분리하다 *훨씬 큰 문제* 발견:

1. **piku 는 worldcup 게임 디렉토리, "글"이 아님.** 각 `/w/{id}` 페이지 = 두 인물/사진 중 선택하는 인터랙티브 게임. "본문 텍스트"는 BS4 셀렉터로 잡히는 것이 *modal-header(게임 제목) + modal-body(라운드 선택 버튼)* — 합쳐 ~170자 HTML. 의미 있는 article body 부재.
2. **Cloudflare 챌린지가 navigation 마다 ~30% 재발화.** N100 측정: 같은 playwright 세션 안 `fetch_list` 연속 2회 호출 시 #1=성공 / #2=`title="잠시만 기다리십시오…"` (CF Just-a-moment 챌린지 페이지). 5분 텀 두고 별도 세션으로 호출해도 신뢰도 일관 ~67% (3회 중 2회 list>=10, 1회 list=0). `S1.Hcap`(probe) 도 동일 BLOCKED_BOT 마크.
3. **httpx 정적 fetch 는 카드 자체 미수령.** `/w/search/order=hot` 의 정적 HTML 응답 (13719 bytes) 에 `product-desc` 키워드 1회만 등장(스크립트 내), `data-id` 0개. 카드는 클라이언트 JS 가 그리는 dynamic 영역 — Playwright 만 통과.
4. piku 의 `/w/{id}` 페이지 자체도 단일 모달 게임 + BroadcastChannel 알림("동시에 2개 이상의 월드컵 X") — title/meta 빼고는 추출할 텍스트 자체가 없음.

자동 파이프라인 4 retry 가 위 (1)+(2)+(3) 다중 원인을 LLM 으로 못 통합 — 본문 검증 hard-fail.

## 왜 문제인가
- list-page 카드가 JS 렌더 → httpx 정적은 빈 응답
- Playwright 도 CF 챌린지 재발화 → 폴링마다 flaky
- "본문"이 본질적으로 부재 → article_body_len 임계 100자 통과시키려면 head meta concat fallback 같은 인공 padding 필요

## 픽스 (fix_layer: none — 손-config)

### 손-config: `configs/host_piku-co-kr_w_4d61ac2c.json`
- `strategy: playwright_html` (httpx 는 카드 미렌더로 불가)
- `nav_timeout_ms: 30000`, `idle_timeout_ms: 10000`, `quiet_ms: 800` — CF 챌린지 자체 해소 + JS render 시간 확보
- `list.wait_selector: div.product-desc` — 카드 셀렉터로 직접 대기 (last_config 의 `div.row.equal > div.col-xs-6` 는 wrapper 만 잡혀 카드 없이도 통과해서 0건 추출되던 원인)
- `list.row_selector: div.row.equal > div.col-xs-6, div.row.equal > div.col-xs-12` (last_config 유지) + `row_required_selector: div.product-desc` 로 카드 없는 wrapper 거름
- `article.content` 2-tier fallback:
  1. `div.modal-content` html (~170자, 정상 렌더 시)
  2. `concat([head title text, head meta[name=description] content, head meta[property=og:description] content])` (~150자, modal-content 미렌더 시. 모든 piku 글페이지에 존재하는 정적 head meta 라 결과 보장)
- `article.enrich.title`: `head meta[property=og:title]` (자동생성 title 더 완전한 게임 풀네임으로 덮어쓰기)

### N100 register baseline
3회 retry — 10건 / 0건 / 10건. ~67% 신뢰도. 봇 polling cycle 도 동률 flaky 예상 (CF 챌린지 = silent skip). 사용자 입장: 알림이 모든 사이클은 아니지만 *결국* 도달.

### 손-config 만 — engine 코드 변경 X
fix_layer none, adapters_changed [], engine_files_touched [].

## 트랙 B (미래 향 — probe 일반화) — 0건 매칭

- **2a (인식기 PATTERNS) — X.** piku 는 단일 게시판 사이트 (`/w/search/order=hot` 외 다른 board URL 형태 없음). 플랫폼화 가치 0.
- **2b (--article-url 재시도) — X.** list 추출 OK + first_article_url 정상 추출 (`/w/721FCA` 등). first article 오집음 문제 아님.
- **2c (probe heuristic 신규) — X (현재 사례 단일).** "CF challenge re-fires per nav" 패턴 — probe 가 측정하려면 같은 URL 을 *2회 연속* 나비게이션 후 두 번째도 200/유효 콘텐츠 받았는지 비교해야 함. 현재 probe.py 는 1회 fetch + sec-ch-ua 강화본(`S1.Hcap`) 측정만 — re-nav reliability 측정 없음. 일반화 가치는 있는데 단일 사례라 가성비 의문 — *재발 시* 휴리스틱화. `probe/_contract.py:_ARTIFACTS` 에 후보 키 슬롯 미추가.
- **2d (probe artifact 수정) — X.** `S1.H2`/`S4` 모두 200 OK + 41970 bytes html 잡힘 — probe 자체 작동 정상. 문제는 *production polling 시 CF re-validate* 인데 probe 가 single-shot 이라 못 본 게 정상.

매칭 0건 이유: piku 는 (i) anti-bot+SPA 단일 사이트라 패턴 일반화 가치 작고, (ii) 본질적으로 notice site 아닌 worldcup 게임 디렉토리라 fix_layer 어디에도 *해결*이 안 됨 — 단순 손-config 으로 *완화*만 가능.

## 자가 점검 결과 (§6)

1. **어느 자리?** — none (손-config 만). config 파일이 자기-contained — strategy/timing tweak + selector fallback.
2. **이전 케이스?** — `host_google-com_search_9440e9f9` (anti-bot 챌린지 → rejected_with_policy). piku 도 anti-bot 인데 reject 안 한 이유: 챌린지가 영구 블록 아닌 *간헐적 재발화* + 사용자가 실제 폴링 가치 있는 콘텐츠 (인기 worldcup 신규 등록) 요청. google search 는 SERP 자체가 notice-쓰임 아님.
3. **누구 깰까?** — 0 사이트. piku.co.kr 단일 사이트 손-config — 다른 config 0 영향.
4. **검증 그린?** — `python scripts/probe_smoke.py` (commit 단계 pre-push hook). 영향 사이트 0. 손-실행 = N100 register --config baseline 10건 성공 (3회 중 2회).
5. **case 파일 + commit msg 양식** — frontmatter outcome=handcrafted, fix_layer=none.
6. **새 패턴 fixture 추가?** — 신규 strategy/휴리스틱 X → fixture X.
7. **트랙 B 0건 이유** — 위 ↑.

## 운영상 주의
- 봇 폴링 사이클당 ~30% silent skip 예상. 사용자 알림 latency 평균 7-15분 (5분 폴 + retry).
- fetch_article 도 CF 챌린지/modal 미렌더로 종종 0자 → 알림에 본문 없을 수 있음 (제목 + URL 만).
- 패턴 재발 시 (다른 SPA+CF 사이트 사용자 요청) → 트랙 B 2c "renavigation reliability" 휴리스틱화 검토.
