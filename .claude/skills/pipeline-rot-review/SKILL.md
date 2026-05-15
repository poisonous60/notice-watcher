---
name: pipeline-rot-review
description: >-
  prompts/config_writer.* + cases + schema + few-shot 의 누적 rot 진단 — 죽은 룰 (참조 끊긴 file/key),
  중복, 모순, 과spec 4종 검출. 사용자가 "rot 점검", "프롬프트 누더기 점검", "/pipeline-rot-review" 라고 할 때.
  read-only — Claude 가 발견 보고 후 사용자 승인 받고 적용. 자동 수정 X.
  이 프로젝트 (`poisonous60/notice-watcher` 의 dev박스 clone) 전용. hand-config 의 *additive* prompt 변경과
  분리 — 이 SKILL 은 *curative* (제거/병합/정리). 자세히는 `docs/자가개선 인프라 계획.md` §1b.
---

이 프로젝트는 LLM 이 사이트 probe digest 를 보고 config JSON 을 생성한다 (`scripts/register.py` → `prompts/config_writer.system.txt`).
`hand-config` 워크플로 가 운영되면서 prompt 에 *룰 추가* 가 누적된다. 이 SKILL 은 그 누적이 ① 죽은 참조, ② 중복, ③ 모순,
④ 과spec (= 9 cases 다 같은 방향인데 조건부로 적힌 룰) 을 만드는지 *능동적으로 점검*해서 사용자에게 보고한다.

## 트리거

사용자가 다음과 같이 호출:
- `/pipeline-rot-review`
- "rot 점검", "프롬프트 누더기 점검", "프롬프트 정리 좀"
- 케이스 50+ 누적 또는 `prompts/config_writer.system.txt` 200줄+ 도달 시 (자동 알림은 X — 사용자가 손-실행)

> **트리거 미달 상태에서도 작동**. clean 이면 `rot 없음 ✅` + audit trail (점검 항목 카운트) 출력. 첫 run = baseline.

## 점검 대상 (5 영역)

| 영역 | 파일 | 의미 |
|---|---|---|
| **system 룰** | `prompts/config_writer.system.txt` | LLM 의 기본 룰 셋 |
| **retry feedback** | `prompts/config_writer.retry_skeleton.txt` | 실패 시 LLM 에 보여주는 feedback 템플릿 |
| **user input** | `prompts/config_writer.user_skeleton.txt` | digest 를 LLM 에게 어떻게 펼쳐 보일지 |
| **schema** | `engine/config_schema.py` | config 스키마의 strict 룰 (룰 vs schema mismatch 검출) |
| **few-shot** | `generate/prompt.py` 의 `_EXAMPLE_CONFIG_FILES` | LLM 에 보여주는 예시 config |
| **cases** | `docs/cases/*.md` (현재 9건) | 누적 hand-config 케이스 — 룰의 *실제 효과* 검증 baseline |

## 검출 4종

### 1. 죽은 룰 (dead reference)
system.txt 의 룰이 *backtick 으로 인용한* file/key/concept 가 실제 코드에 더 이상 X.

예: `"` known_platforms.py `"` 참조 — commit `eab9164` 에서 `engine/recognizers/<plat>.py` 패키지로 분리됨 (이미 처리됨, audit baseline)

검출 절차:
- system.txt + retry_skeleton.txt 의 backtick 인용 추출 (`grep -oE '` `[^` `]+` `'`)
- 각 인용에 대해 코드 base 에 존재 확인 (file path → `Glob`, function/key → `Grep`)
- 0 매칭 = 죽은 참조

### 2. 중복 (redundant)
두 줄/섹션이 같은 instruction 반복.

예: section A "JSON API 우선" + section B "traffic_json_api_candidates 가 있으면 그것을 본다" — 같은 의미 다른 표현

검출 절차:
- system.txt 의 각 bullet/문장 단위로 split
- key concept 추출 (예: "JSON API", "traffic_json_api_candidates", "row_selector", "post_id 필수")
- 같은 concept 가 ≥2 위치에 등장하면 중복 후보 → 사용자에게 보고 ("정말 다른 의미인가" 판단 위임)

### 3. 모순 (contradiction)
같은 조건에 대해 다른 권장.

예: section X "SPA 면 playwright_html" + section Y "SPA 라도 본문이 JSON 이면 httpx_html + article.fetch_kind:json" — 두 룰이 SPA 처리 갈래 다름. 모순일 수도, 맥락 분기일 수도 → 사용자 판단

검출 절차:
- 조건+권장 패턴 추출 (예: "if SPA → playwright_html", "if SPA + JSON body → httpx_html")
- 같은 조건 다른 권장 매칭

### 4. 과spec (over-specified)
조건부 룰이 9 cases 모두 같은 방향 → 조건 무의미.

예: "if X 사이트면 Y 룰" 이 9 cases 다 X 만족 → "Y 룰" 만 남기면 됨

검출 절차:
- system.txt 의 conditional ("만약 ~~", "if ~", "~~ 인 경우") 룰 추출
- 9 cases 의 frontmatter (`config_strategy`, `failure_keys`, `tags`) 분포와 비교
- 분기 무의미 → 단순화 권장

## 단계

1. 5 영역 + cases 파일 모두 Read (또는 Grep 으로 키 단위 추출)
2. 각 검출 카테고리 적용 (4종)
3. 발견 list 작성 — 위치 + 종류 + 권장 한 줄
4. 사용자에게 보고 (출력 형식 ↓)
5. 사용자 승인 시 — Claude 가 prompt 수정 (SKILL 자체 자동 수정 X, 별도 Edit 호출)

## 출력 형식 (idempotent)

### Clean 시
```
[pipeline-rot-review] rot 없음 ✅
점검:
- system.txt: NN 줄 / NN 룰
- retry_skeleton.txt: NN 줄
- user_skeleton.txt: NN 줄
- schema: engine/config_schema.py NN 키
- few-shot: generate/prompt.py 의 _EXAMPLE_CONFIG_FILES NN 예시
- cases: docs/cases/*.md NN 건

모든 backtick 인용 정합. 중복/모순/과spec 후보 0건.
```

### 발견 시
```
[pipeline-rot-review] rot 발견 N건

[죽은 룰] system.txt:NN — `<인용>` 가 코드/schema 에 없음 (commit `<hash>` 이후 제거됨 추정)
  → 권장: 룰에서 인용 제거 또는 `<새 위치>` 로 갱신

[중복] system.txt:AA ↔ system.txt:BB — 같은 의미: <요약>
  → 권장: 한 곳으로 통합 (BB 가 더 명확하면 AA 제거)

[모순] system.txt:XX ↔ retry_skeleton.txt:YY — <조건> 에 다른 권장
  → 권장: 사용자 판단 — 의도된 분기인가 모순인가

[과spec] system.txt:ZZ — `if <조건>` 룰이 9 cases 다 <조건> 만족 → 분기 무의미
  → 권장: 조건 제거, 룰만 유지

점검 영역: system.txt(NN줄), retry(NN줄), user(NN줄), schema(NN키), few-shot(NN예시), cases(NN건)
```

## 검출 로직 한계 (false-negative 인지)

이 SKILL 은 다음을 *못 잡음*:

1. **regex/grep 기반** — 의미적 모순 (개념적으로 충돌하지만 단어가 다름) 못 잡음
2. **자유 prose 죽음** — 룰이 backtick 인용 없이 자유 문장으로 적힌 경우 (예: "엔드필드처럼 SPA 모달인 경우") — file/key 명시 X 라 grep 못 함
3. **cases 부족 시 false-negative** — 9 cases 만으로는 과spec 판단 빈약. 50+ 누적 후 신뢰도 ↑
4. **schema-prompt 모순** — schema 는 strict 한데 prompt 는 lax 한 경우 — 코드 실행 안 하니 못 잡음

→ **사용자 검토 권장**. SKILL 은 *후보 보고*, 최종 판단·적용은 사용자.

## 원칙

- **read-only** — SKILL 자체는 prompt 파일 수정 X. Claude 가 발견 보고 후 사용자 승인 받고 별도 Edit 호출
- **자동 적용 X** — "이거 수정할까요?" 형태로 한 건씩 사용자 승인
- **트리거 미달 시도 작동** — 첫 run = baseline 잡기 목적, clean 이어도 valuable
- **자동 호출 X** — 사용자 명시 호출만. cron/hook 자동 X (UX friction)

## 관련

- `docs/자가개선 인프라 계획.md` §1b, §0c — 이 SKILL 의 설계 배경 (additive vs curative 분리)
- `docs/자가개선 인프라 계획.md` 부록 C — v3 인프라 구현 로그 (이 SKILL 은 그 미래 작업이었음)
- `.claude/skills/hand-config/SKILL.md` — *additive* prompt 변경 워크플로 (이 SKILL 의 반대편)
- `.claude/agents/hand-config-reviewer.md` — hand-config 변경 검토 subagent (이 SKILL 과 평행)
