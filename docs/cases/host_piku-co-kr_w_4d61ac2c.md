---
slug: host_piku-co-kr_w_4d61ac2c
url: https://www.piku.co.kr/w/search/order=hot
status: 🔧 손 config + (E) body_empty_acceptable 플래그 + (C) probe 휴리스틱 2종 (interactive_action + static_vs_headless)
outcome: improved
date: 2026-05-16
requested_by: poi23619
failure_keys: [article_body_len, cf_challenge_renav, body_empty_acceptable_missing, static_verdict_false_positive]
fix_layer: E+A+C+D
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: [engine/config_schema.py, generate/validate.py, prompts/config_writer.system.txt, prompts/config_writer.retry_skeleton.txt, scripts/probe_smoke.py, tests/validate/test_body_empty_acceptable.py, probe/extract.py, probe/diagnose.py, probe/_contract.py, scripts/probe.py, tests/probe_heuristics/test_list_row_interactive_action_text.py, tests/probe_heuristics/test_static_vs_headless_check.py]
tags: [worldcup, game-directory, cloudflare, anti-bot, flaky-polling, SPA, modal-content, non-article-site, body-empty-acceptable, schema-flag, probe-heuristic, verdict-correction, interactive-action, static-vs-headless]
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

## 픽스 (fix_layer: E+A+D — 인프라 보강 + 수동 config 간소화)

### (E) 새 스키마 플래그 `article.body_empty_acceptable: bool`
`engine/config_schema.py` 에 추가. true 면 `generate/validate.py:183` 의 article_body_len 검증이 `hard=False` 로 완화 — 본문이 *본질적으로 없는* 사이트 (검색결과 SERP / 인터랙티브 게임 디렉토리 / 외부 host 행 aggregator / canvas-only SPA) opt-in. 봇은 등록 후 `body_empty_at_baseline=true` 면 "본문 추출 안 됨" 경고를 사용자 메시지에 자동으로 붙임 (`bot/site_ops.py:body_warning`) — 알림은 제목+URL+요약 만 나가도 OK.

이전엔 본문 0자 = `hard=True` → auto-pipeline 4회 retry FAIL → triage 큐 강제 진입. 본문 selector 만 *집착* 하느라 본질 ("이 사이트는 본문 자체 없음") 못 인식. 같은 패턴 사이트들 (`host_google_search`, `host_scholar_google`, 그리고 이번 piku) 모두 같은 함정.

### (A) prompt 룰 추가 (config_writer system + retry skeleton)
- `prompts/config_writer.system.txt` 의 article 키 설명에 `body_empty_acceptable` 한 줄 추가
- `prompts/config_writer.retry_skeleton.txt` 의 "수정 힌트" 에 룰: "본문 검증 article_body_len 가 *직전 2회 이상* FAIL 했고 글페이지 HTML 에 진짜 '글 본문' 자체가 부재 — 사이트가 본문 없는 종류 → `article.body_empty_acceptable: true` 박고 멈춰라. 더 이상 selector 시도 X."

LLM 이 자동 파이프라인 retry 중 2회+ 본문 0자 보면 selector 더 시도 안 하고 flag 박고 마무리 — 같은 패턴 미래 사이트 자동 등록 통과.

### (D) validate.py 의 article_body_len 분기
`generate/validate.py:158-200` — `cfg["article"].get("body_empty_acceptable")` 가 true 면:
- 본문 <100자 → `hard=False` (warn 만, 등록 진행)
- "fetch_article 로 본문을 못 얻음" 도 `hard=False`

기존 `(blen == 0 and fetch_note)` skip_status 분기는 그대로 — 401/403 차단글과 분리.

### 수동 config (간소화): `configs/host_piku-co-kr_w_4d61ac2c.json`
플래그 신설로 fallback 인공 작성 제거 — `article.content` 가 단일 selector (`div.modal-content` html) 만. modal-content 안 떠도 봇이 자동 경고. 단순.

- `strategy: playwright_html` (httpx 는 카드 미렌더로 불가)
- `nav_timeout_ms: 30000`, `idle_timeout_ms: 10000`, `quiet_ms: 800` — CF 챌린지 자체 해소 + JS render 시간 확보
- `list.wait_selector: div.product-desc` — 카드 셀렉터로 직접 대기
- `article.body_empty_acceptable: true` — 본문 없는 사이트 opt-in
- `article.content: [div.modal-content html]` — 단일 selector. 렌더되면 추출, 안 되면 봇 자동 경고
- `article.enrich.title: head meta[property=og:title]` — title 보강

### 테스트
`tests/validate/test_body_empty_acceptable.py` — 5 케이스:
1. flag=true + body 0자 → hard fail 없어야
2. flag=true + body 50자(<100) → hard fail 없어야
3. flag 없음 + body 0자 → article_body_len hard fail (기존 동작 유지)
4. flag 없음 + body 200자 → 모두 pass
5. schema 가 flag 받아들이는지

`scripts/probe_smoke.py` 의 stage 5 가 `tests/validate/` 도 자동 스캔 (`EXTRA_UNIT_TEST_DIRS`). pre-push hook 통해 회귀 방어.

probe_smoke 최종: PASS 257 FAIL 0 WARN 4 (24 파일 · 221 케이스 · 0 FAIL).

### N100 register baseline
3회 retry — 10건 / 0건 / 10건. ~67% 신뢰도. 봇 polling cycle 도 flaky 예상 (CF 챌린지 = silent skip). 사용자 입장: 알림이 모든 사이클은 아니지만 *결국* 도달.

## 트랙 B (미래 향 — 일반화) — 4건 매칭 (E+A+C+D)

**3차 진화:**
- 1차 (커밋 3fe996e): "트랙 B 0건" 결론.
- 2차 (커밋 e18e807): 사용자 피드백 "naver cafe 처럼 본문 없으면 그냥 없는대로 보내면 안 되나" → **(E)+(A)+(D)** body_empty_acceptable 플래그 박음. validate.py hard 완화 길 개통.
- 3차 (이번): 사용자 후속 분류 질문 "단서 증가/필터링/점수 재계산 중 뭐?" → **(C) probe 휴리스틱 2종** 박음. **(A)** 단서 증가 = `list_row_interactive_action_text` + body_empty_likely summary 키 = 1st attempt 부터 flag 자동. **(B)** 단서 필터링 = `static_vs_headless_check` = probe verdict "정적 충분" false positive 정정.

- **2a (인식기 PATTERNS) — X.** piku 단일 게시판, 플랫폼화 가치 0.
- **2b (--article-url 재시도) — X.** list/first_article_url 정상.
- **2c (probe heuristic 신규) — O 2종.**
  - **`list_row_interactive_action_text`** (단서 증가) — `html_repeating_patterns` 의 `first_text` 안 액션 UI 키워드 (이상형월드컵/시작하기/랭킹보기/투표/Vote now/Round 1 등 KO+EN) ≥2개 매칭 = 본문 없는 사이트. piku artifact 로 retroactive 검증 — `is_interactive_action=true, matched_keyword_set=['랭킹보기','시작하기','월드컵','이상형 월드컵']` 매칭. 일반 게시판 (글 제목 list) 안 매칭.
  - **`static_vs_headless_check`** (단서 필터링) — 정적 응답 size 와 Playwright 응답 size 비교 + `data-id=`/`<a ` count 차이. ratio≥2.0 AND row_signal_diff≥5 면 `static_insufficient=true`. piku artifact 로 retroactive 검증 — `ratio=3.26 (static 12kb vs headless 41kb), row_signal_static=5, row_signal_headless=55, static_insufficient=true`.
- **2d (probe artifact 수정) — O.** `list_candidates.json` 에 `row_interactive_action`/`body_empty_likely` 키 신규 추가 + `diagnose.py` 의 verdict 결정 분기에 `static_vs_headless_check` 호출 — static_insufficient=true 면 `static_ok=[]` 강제 무효화 + verdict 정정 + notes 추가.
- **(E) schema 거부 — O (2차).** `article.body_empty_acceptable` 플래그.
- **(A) system 룰 추가 — O.** prompt 에 `body_empty_likely` 키 등장 룰 추가 — 1st attempt 부터 flag 박게.
- **(D) retry feedback — O (2차).** "본문 검증 2회+ FAIL + 본문 자체 부재 → flag 박고 멈춰라" 룰.

### 효과 비교
| 단계 | piku-패턴 사이트 등록 흐름 |
|---|---|
| 1차 전 (커밋 d202fa5) | auto-pipeline 4회 retry FAIL → triage 진입 → 사용자 수동 config 필요 |
| 2차 후 (e18e807) | auto-pipeline 1-2회 retry 후 LLM 이 flag 박음 → 등록 OK |
| 3차 후 (이번) | probe digest 의 `body_empty_likely=true` + verdict "JS 실행 필요" → LLM 1st attempt 부터 flag + playwright_html → 등록 OK (retry 0) |

## 자가 점검 결과 (§6) — 재검토판 (사용자 피드백 후)

1. **어느 자리?** — E (schema) + A (system 룰) + D (retry feedback). 1차 결론 "none (수동 config)" 은 잘못 — `article_body_len, hard=True` 자체가 막혀 있던 거였음.
2. **이전 케이스?** — `host_google_search_9440e9f9` (anti-bot SERP, rejected_with_policy), `host_scholar_google_706d9c49` (aggregator, list_row_external_host C+D fix), `naver-cafe_31104609_1` (body_empty_at_baseline 봇 경고 시스템 F). 이번 (E) 가 그 셋의 *위쪽 공통 패턴* — "본문 없는 사이트 자동 등록 통과 길 개통".
3. **누구 깰까?** — 0 사이트. 기존 21+ configs 는 article.body_empty_acceptable 기본값 false → 동작 불변. flag opt-in 패턴이라 누락 위험 없음.
4. **검증 그린?** —
   - `python scripts/probe_smoke.py` PASS 257/0/4/0 (4 WARN = 기존 fixture probe artifact 옛것, 무관)
   - `python tests/validate/test_body_empty_acceptable.py` 5/5 PASS
   - 영향 사이트 0 — 기존 configs flag 없으니 옛 동작
   - 손-실행 N100 register baseline 10/0/10 (이번 PR 이전 측정, config 본질 변화 X)
5. **case 파일 + commit msg** — frontmatter outcome=improved (였던 handcrafted 에서 격상 — 인프라 일반화 박음), fix_layer=E+A+D, commit msg prefix `[fix-layer: E+A+D]`.
6. **새 패턴 fixture 추가?** — `tests/validate/test_body_empty_acceptable.py` 신규 — probe_smoke stage 5 의 `EXTRA_UNIT_TEST_DIRS` 통해 회귀 방어. 새 strategy/휴리스틱은 아니라 probe_heuristics fixture 는 X.
7. **트랙 B 매칭 이유** — 위 §트랙 B 참조.

## 운영상 주의
- 봇 폴링 사이클당 ~30% silent skip 예상 (CF 챌린지). 사용자 알림 latency 평균 7-15분.
- fetch_article 도 CF 챌린지/modal 미렌더로 종종 0자 → 알림에 본문 없을 수 있음. 봇이 `body_warning(slug)` 으로 "⚠️ 본문 추출 안 됨" 자동 표시.
- 패턴 재발 시 (다른 SPA+CF 사이트) → trigger 적으면 수동 config + body_empty_acceptable, 자주 들어오면 (C) "renavigation reliability" probe 휴리스틱화 검토.

## 교훈
30분 수동 config 작업 후 사용자 한 줄 질문 ("naver cafe 처럼 본문 없으면 그냥 없는대로 보내면 안 되나") 으로 (E)+(A)+(D) 진짜 픽스 자리 발견. 또 한 줄 질문 ("단서 증가/필터링/점수 재계산 중 뭐?") 로 *probe verdict false positive (단서 필터링 미흡)* 발견 — (C) 휴리스틱 2종 박음. 1차에 "트랙 B 0건 매칭" 결론 낼 때 *왜* 검증 자체가 hard=True 인지, *왜* probe 가 "정적 충분" 박았는지 의심 안 한 게 패착.

**다음 사례부터 체크:**
1. hard fail 항목 만나면 "이 hard 가 정당한가, opt-out 길은 있는가" 1초 물어보기.
2. probe verdict (recommended_strategy, "정적 충분" 등) 이 옳은지 *원본 응답과 대조* — HTTP status 만 보면 false positive 발생 (콘텐츠 양/구조 차이 무시).
3. fix-layer 분류를 (1) 단서 증가 / (2) 단서 필터링 / (3) 단서 점수 재계산 중 어디 박을지 명시 — (1) 만 자꾸 박으면 누더기, (2)+(3) 가 시급한 경우 많음.
