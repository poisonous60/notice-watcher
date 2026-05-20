# case `outcome` 분류 — mechanism 기반 (즉답 vs 추론개선), scope 기반 X

## Context

`docs/cases/<slug>.md` frontmatter 의 `outcome` enum (hand-config 스킬 §6.5, `case_log.py`, `cases.sqlite3`, dashboard `/cases`) 가 hand-config 한 사이클의 결과를 분류한다. 핵심 두 값:

- `improved` — "fix_layer 기반 코드 일반화 + 효과"
- `handcrafted` — "손-config/손어댑터 — 그 사이트만 (fix_layer X)"

이 정의는 **scope 로 가른다** — "그 사이트만이냐, 일반화됐냐". 그래서 config 발급 recognizer (arca/google-news/naver-blog/tistory/discourse — 플랫폼 전체 커버, fix_layer F) 는 `improved` 로 박혔다.

문제: recognizer 가 하는 일은 **URL 패턴 매칭 → 미리 박은 config 즉시 발급** = dispatch table 이다. register 의 추론(probe→gpt-5.4-mini)을 *1도 안 똑똑하게 함* — 미지의 사이트엔 아무것도 안 하고 fall-through. 즉 **단일 config 의 parameterized 버전**일 뿐, "개선" 이 아니다.

증거 — 분류가 이미 깨져 있었다: `arca-live_trickcal` 은 `handcrafted` (fix_layer=`-`), `google-news` 은 `improved` (fix_layer F). 둘 다 플랫폼 config 발급(arca 도 `arca_live.py` recognizer 보유)인데 한쪽 handcrafted, 한쪽 improved.

## Decision

`outcome` 의 의미축을 **scope → mechanism 으로 re-cut** 한다. 기준 질문: **"이 case 의 *주된* 산출이 AUTO 추론을 똑똑하게 했나(=미지 사이트 처리 능력↑), 아니면 아는 것에 답을 박았나(=즉답)?"**

| outcome | 의미 (재정의) | 자리 |
|---|---|---|
| `improved` | **추론 개선** — AUTO path(probe 추출·LLM 생성·검증·게이트)가 *미지* 사이트를 더 잘 풂 | C(probe 휴리스틱)·E(schema)·A(prompt)·D(retry)·reject-gate recognizer·register 플로우·blacklist 학습 |
| `handcrafted` | **즉답** — 아는 것에 사람이 답 박음 (추론 bypass) | 단일 config(URL 1개)·플랫폼 config(config 발급 recognizer)·손-adapter |
| `rejected` / `rejected_with_policy` | 거부 리스트 등록 | policy/gate reject |

- 폐기: "handcrafted = fix_layer X" — 플랫폼 config 는 `handcrafted` + fix_layer F 다. scope(단일 vs 플랫폼)는 `fix_layer` + recognizer 유무로 복구.
- `improved` = **dashboard "파이프 진보" 의 유일한 신호**. handcrafted·rejected 는 "처리는 했으나 파이프 안 변함" — 따로(toil/거부).
- mixed case (즉답+추론개선 섞임 — 예: google-news = recognizer + 손-adapter + `_STABLE_ID_RE` cap fix) → **dominant mechanism** 으로 1값. google-news 의 main = 플랫폼 config 즉답 → `handcrafted`.

어휘는 `CONTEXT.md` 에 박음 (즉답 / 추론 개선 / 단일 config / 플랫폼 config / recognizer 2종).

## Why

`outcome` 의 목적 = "파이프라인이 *나아지고* 있나" 측정. "코드 일반화돼서 미래 toil 줄임" 은 즉답(플랫폼 config)도 충족하지만 — 그건 *아는 클래스* 의 toil 만 줄임. 미지 사이트 처리 능력(=진짜 파이프 진보)은 추론개선(C/E/A/D…)만 늘린다. scope-cut 은 이 둘을 뭉개 "recognizer 추가 = 개선" 으로 오표시한다.

mechanism-cut 은 truthful: dispatch table 추가를 "개선" 이라 부르지 않는다. dashboard 의 improved 카운트가 "시스템이 똑똑해진 양" 을 정직하게 반영.

## Considered Options

- **scope-cut 유지 (현행)** — improved=일반화(scope 넓음), handcrafted=단일. 기각: recognizer(즉답)를 improved 로 오표시, arca/google 비대칭 이미 발생, "개선" 신호 오염.
- **3-value 확장 (`platform_config` 신설)** — 단일/플랫폼/추론개선 3칸, 정보 손실 0. 기각: `case_log.py` CHECK + dashboard + docs + DB 다 건드림 (큼). scope 는 fix_layer 로 복구 가능해 2-value 로 충분. (사용자 결정 2026-05-20)
- **outcome 폐지, fix_layer 로만 분류** — 기각: fix_layer 는 *코드 자리*(A~F)지 mechanism 아님. F 가 즉답(recognizer)·메커니즘(adapter)·추론(register flow) 다 걸쳐 1:1 안 됨.

## Status

**Decision 합의 (2026-05-20). 마이그레이션 미실행 — 다음 세션 예정.** 실행 항목: `docs/B-task_outcome-migration.md` 참조 (SKILL §6.5 enum 재정의 + recognizer 6 case frontmatter improved→handcrafted + `cases_index.py --backfill-db` + dashboard label 확인).
