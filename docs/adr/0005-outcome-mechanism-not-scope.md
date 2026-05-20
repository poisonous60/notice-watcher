# case `outcome` 분류 — mechanism 기반 (추론 개선 vs 수동 config), scope 기반 X

## Context

`docs/cases/<slug>.md` frontmatter 의 `outcome` enum (hand-config 스킬 §6.5, `case_log.py`, `cases.sqlite3`, dashboard `/cases`) 가 hand-config 한 사이클의 결과를 분류한다. 핵심 두 값:

- `improved` — "fix_layer 기반 코드 일반화 + 효과"
- `handcrafted` — "손-config/손어댑터 — 그 사이트만 (fix_layer X)"

이 정의는 **scope 로 가른다** — "그 사이트만이냐, 일반화됐냐". 그래서 config 발급 recognizer (arca/google-news/naver-blog/tistory/discourse — 플랫폼 전체 커버, fix_layer F) 는 `improved` 로 박혔다.

문제: 이 프로젝트의 궁극 목적은 **자동 register 가 모든 사이트 유형을 스스로 생성/거부** 해서 triage 큐엔 *처음 보는 새 패턴만* 쌓이게 하는 것이다. 그 관점에서 — config 발급 recognizer 가 하는 일은 **URL 패턴 매칭 → 미리 박은 config 즉시 발급** = dispatch table 이다. register 의 자동 추론(probe→gpt-5.4-mini)을 *1도 안 똑똑하게 함*. 미지 유형엔 아무것도 안 하고 fall-through. 즉 **단일 config 의 parameterized 버전**일 뿐 — 자동 솔버가 똑똑해진 "개선" 이 아니라, 자동이 못 푼 걸 사람-루프가 직접 박은 *패치*(수동 config) 다.

증거 — 분류가 이미 깨져 있었다: `arca-live_trickcal` 은 `handcrafted` (fix_layer=`-`), `google-news` 은 `improved` (fix_layer F). 둘 다 config 발급 recognizer(arca 도 `arca_live.py` 보유)인데 한쪽 handcrafted, 한쪽 improved.

## Decision

`outcome` 의 의미축을 **scope → mechanism 으로 re-cut** 한다. 기준 질문: **"이 case 의 *주된* 산출이 자동 솔버를 똑똑하게 했나(=미지 유형 처리력↑ = 진보), 아니면 자동이 못 푼 걸 직접 박았나(=수동 config 패치)?"**

| outcome | 의미 (재정의) | 자리 |
|---|---|---|
| `improved` | **추론 개선** — 자동 솔버(probe 추출·LLM 생성·검증·거부 게이트)가 *미지* 유형을 더 풂. **유일한 진보** | C(probe 휴리스틱)·E(schema)·A(prompt)·D(retry)·거부 필터(`recognize_reject`)·register 거부 게이트·blacklist 학습 |
| `handcrafted` | **수동 config** — 자동이 못 푼 걸 직접 박은 패치 (진보 X) | 단일 config(URL 1개)·플랫폼 config(config 발급 recognizer)·손-adapter |
| `rejected` / `rejected_with_policy` | 거부 리스트 등록 | policy/gate reject |

- 폐기: "handcrafted = fix_layer X" — 플랫폼 config 는 `handcrafted` + fix_layer F 다. scope(단일 vs 플랫폼)는 `fix_layer` + recognizer 유무로 복구.
- `improved` = **dashboard "파이프 진보" 의 유일한 신호**. handcrafted·rejected 는 "그 건은 처리했으나 자동 솔버는 그대로" — 따로(패치/거부).
- 플랫폼 config 도 handcrafted — 커버리지는 넓혀도 자동 추론은 안 변함. **나쁨의 결** (case body 1줄): (a) 추론 개선 가능했는데 안 함 = 게을렀음(트랙 B 재도전 후보) / (b) 추론 원천 불가(arca Cloudflare·google ToS·anti-bot) = recognizer 가 유일 경로(영구 종결).
- mixed case (수동+추론개선 섞임 — 예: google-news = recognizer + 손-adapter + `_STABLE_ID_RE` cap fix) → **dominant mechanism** 으로 1값. google-news 의 main = 플랫폼 config 패치 → `handcrafted`.

어휘는 `CONTEXT.md` 에 박음 (등록 실패 / 추론 개선 / 수동 config / 단일 config / 플랫폼 config / recognizer 2종).

## Why

`outcome` 의 목적 = "자동 파이프라인이 *나아지고* 있나" 측정 (= triage 큐가 새 패턴만 남게 가까워지나). "코드 일반화돼서 미래 toil 줄임" 은 플랫폼 config 도 충족하지만 — 그건 *아는 클래스* 의 toil 만 줄인다. 미지 유형 처리력(=진짜 진보)은 추론개선(C/E/A/D…)만 늘린다. scope-cut 은 이 둘을 뭉개 "recognizer 추가 = 개선" 으로 오표시한다.

또 hand-config 가 수동 config 를 만든다는 것 자체가 *그 요청은 한 번 자동 처리 실패* 했다는 뜻 — "개선" 으로 셀 수 없다. mechanism-cut 은 truthful: dispatch table 추가를 "진보" 라 부르지 않는다. dashboard 의 improved 카운트가 "시스템이 스스로 똑똑해진 양" 을 정직하게 반영.

## Considered Options

- **scope-cut 유지 (현행)** — improved=일반화(scope 넓음), handcrafted=단일. 기각: 플랫폼 config(패치)를 improved 로 오표시, arca/google 비대칭 이미 발생, "진보" 신호 오염.
- **3-value 확장 (`platform_config` 신설)** — 단일/플랫폼/추론개선 3칸, 정보 손실 0. 기각: `case_log.py` + dashboard + docs + DB 다 건드림(큼). scope 는 fix_layer 로 복구 가능해 2-value 로 충분. (사용자 결정 2026-05-20)
- **outcome 폐지, fix_layer 로만 분류** — 기각: fix_layer 는 *코드 자리*(A~F)지 mechanism 아님. F 가 수동 config(recognizer)·메커니즘(adapter)·추론(register flow) 다 걸쳐 1:1 안 됨.

## Status

**Decision 합의 (2026-05-20). 마이그레이션 미실행 — 다음 세션 예정.** 실행 항목: `docs/B-task_outcome-migration.md` 참조 (SKILL §6.5 enum 재정의 + config 발급 recognizer 6 case frontmatter improved→handcrafted + `cases_index.py --backfill-db` + dashboard label 확인).
