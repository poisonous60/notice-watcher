---
slug: infra_selector_compile_validate_2026-05-21
url: https://www.etoland.co.kr/
status: ✅ E-게이트 — 미escape CSS 선택자(Tailwind `.1.5`)를 validate 시점에 거부 → 런타임 SelectorSyntaxError 크래시(rc=1) 봉합, retry feedback 회수
outcome: improved
date: 2026-05-21
fix_layer: E
failure_keys: [fetch_list]
config_strategy: none
adapters_changed: []
engine_files_touched: [engine/config_schema.py]
tags: [schema-validate, css-selector, soupsieve, tailwind, retry-feedback, batch-2026-05-21-forums]
---

## 무엇이 일어났나

`catalog=2026-05-21-forums` 의 etoland(`www.etoland.co.kr`) 가 rc=1 로 *크래시*:
```
실행 실패: SelectorSyntaxError: Malformed class selector at position 25
main article ul.space-y-1.5 > li
                         ^
[FAIL] fetch_list: ...
```
LLM 이 Tailwind 클래스 `space-y-1.5` 를 그대로 박았는데, 엔진의 매처(bs4 `.select` = **soupsieve**)는
`.5` 를 *숫자로 시작하는 클래스* 로 보고 `SelectorSyntaxError` 를 던진다 (CSS 에서 클래스의 `.` 은
`\.` escape 필요 — `space-y-1\.5`). 이 예외가 `fetch_list` 도중 *제어 흐름 밖* 으로 터져 register 가
rc=1 크래시 → retry 회복 루프조차 안 탐.

### 진단 (§2 진입 강제 인용)

1. last_feedback `[FAIL]`: `[FAIL] fetch_list: 실행 실패: SelectorSyntaxError: Malformed class selector at position 25`
2. diagnosis verdict: `정적 HTTP로 충분` (probe 가 `ul.space-y-1.5 > li` 46행, 실제 `/view/` 링크 추출 — 목록은 정적에 있음)
3. 실패케이스 §매칭: 신규 — 선택자 *컴파일* 단계 크래시 (값 검증 catalog 에 없던 카테고리)
4. 분기: **E (schema 거부)** — 선택자는 config 파일만 보고 컴파일 검증 가능 (soupsieve.compile). 2c(probe 휴리스틱) 기각 — 추출 신호 문제 아님, LLM 출력 문법 문제.
5. 누적 cross-check: `query --failure-key fetch_list` = 0건 (첫 사례, deferred OK였으나 사용자 지정 영구 게이트 우선 [[feedback-prefer-permanent-gate-over-one-shot]])
6. preflight: `miss` — recognize None, failed_at(2026-05-20) 이후 선택자-관련 회복 commit 없음 (xenforo commit 무관) → §2 진입.

## 무엇을 바꿨나 (단일 영구 게이트, fix_layer E)

### `engine/config_schema.py` — `_check_css_selector(sel, where, errs)` 신규
- 선택자 문자열을 엔진과 *동일한 매처* `soupsieve.compile(sel)` 로 검증. `SelectorSyntaxError` 면
  err 추가 (escape 힌트 포함: "Tailwind 숫자 클래스의 점은 `\.` escape"). soupsieve 미설치 시 skip.
- `:self`/생략(=행 자체)·비문자열은 검증 skip (오거부 X).
- 호출 자리 2곳:
  - `_check_source` 의 css/attr 분기 — field/article content/enrich 선택자 (기존 경유).
  - `validate_config` list 분기 — `row_selector`/`row_required_selector`/`exclude_selector`/
    `wait_selector` (field source 아닌 top-level 선택자 — etoland 가 크래시난 자리).

### D-layer 자동 연동 (코드 변경 X)
- `generate/generator.py:233` 이미 `ConfigError → prev_feedback = "config 가 스키마 검증에 실패했다.
  반드시 고쳐라:\n{e}"` 로 retry 회수. E-게이트가 던지는 escape 힌트가 그대로 LLM 다음 attempt 에 감.

## 검증

- 미escape `ul.space-y-1.5 > li` → `ConfigError`(escape 힌트). escape 형 `ul.space-y-1\.5 > li` → 통과.
- `register.py --reuse-probe etoland` 재시도 — **크래시 사라짐**: attempt 3 가 escape 형
  `ul.space-y-1\\.5 > li` 박음(힌트 적용 확인) → 실패 사유가 rc=1 크래시 → 정상 `posts_nonempty: 0건`
  retry 루프로 강등 (etoland root 는 별개 이유로 미등록 — ↓ 박스).
- `probe_smoke.py --stage 3 --stage 5` PASS — 기존 94 configs 전수 validate 무회귀(오거부 0),
  stage 5 새 fixture 5케이스 통과 (58 파일·651 케이스·0 FAIL).
- 새 fixture: `tests/validate/test_selector_compile.py` (정상/미escape row_selector/미escape field/
  escape형/`:self` 5케이스).

## outcome = improved (handcrafted 아님)

generic 추론(검증 layer)의 개선 — *특정 사이트 dedicated adapter 없이* "LLM 이 미escape CSS 선택자를
박는다" 는 **유형** 을 봉합. 모든 Tailwind/숫자-fraction 클래스 사이트에 적용. fix_layer E + 거부/검증
layer = improved (CONTEXT.md outcome 표). etoland 단일 사이트를 푼 게 아니라 *선택자 컴파일 크래시
클래스* 를 푼 것.

## etoland root 자체는 미등록 (별개 사유 — 이 PR scope 밖)

etoland.co.kr `/` 는 **홈페이지 위젯 혼합** — `ul.space-y-1.5` 가 hotdeal/hit/sidebar 등 이질
위젯에 재사용되는 Tailwind utility 클래스라 root 에서 깨끗한 보드 목록이 안 나옴 (humoruniv·bobaedream
와 같은 *board URL 필요* 부류, [[project-forums-batch-2026-05-21]]). 보드 전용 URL(`/hit/list` 등)로
재시도하거나 수동 config 가 답 — 선택자 *크래시* 문제와 무관해 본 E-게이트 scope 밖. **의도적으로 분리.**

## 트랙 B 검토

이 변경 자체가 트랙 B (선택자 escape 크래시 재발 차단, 영구 게이트). 추가 일반화 불필요.
