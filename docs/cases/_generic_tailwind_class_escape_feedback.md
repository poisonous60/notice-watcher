---
slug: _generic_tailwind_class_escape_feedback
url: etoland.co.kr + outfit7.com/news
status: 🟢 improved (Tailwind selector escape feedback generalized)
outcome: improved
date: 2026-05-27
fix_layer: A+D
failure_keys: [selector_compile_failed, tailwind_class_unescaped]
engine_files_touched: [engine/config_schema.py, prompts/config_writer.system.txt]
tags: [tailwind, selector, escape, prompt, validate-feedback]
trigger_slugs: [host_etoland-co-kr_<board>, host_outfit7-com_news_bc877d75]
---

# Tailwind utility class escape feedback

## 증상

두 번째 독립 사례가 들어와 `selector_dot_escape_feedback` 보류 후보를 A+D layer 로 올렸다.

- etoland: `ul.space-y-1.5` 의 점이 escape 되지 않아 soupsieve 가 `.5` 를 malformed class selector 로 해석했고, fetch_list 가 rc=1 로 실패했다.
- outfit7: `:aspect-w-1` 이 leading pseudo-class 처럼 출력되어 soupsieve `NotImplementedError` (`Pseudo-class ':aspect-w-1' not implemented`) 로 실패했다. agentic retry 도 schema feedback 이 colon-variant escape 를 가르치지 못해 max_cycles 로 종료했다.

root-cause 는 사이트별 selector 가 아니라 Tailwind utility class 를 CSS selector 로 옮길 때 필요한 escape 규칙 누락이다. 숫자 dot(`space-y-1.5`)은 `\.`, responsive/state colon variant(`lg:flex`, `hover:bg-blue`)는 `\:` 가 필요하고, `:aspect-w-1` 처럼 `.` 없이 시작하면 class 가 아니라 pseudo-class 로 컴파일된다.

## 수정

- A-layer: `prompts/config_writer.system.txt` 의 row selector 지침에 Tailwind dot/colon escape 예시를 추가했다. `space-y-1.5` → `.space-y-1\.5`, `gap-2.5` → `.gap-2\.5`, `lg:flex` → `.lg\:flex`, `hover:bg-blue` → `.hover\:bg-blue`, 조합형 `.lg\:space-y-1\.5` 를 명시했다.
- D-layer: `engine/config_schema.py:_check_css_selector` 의 `SelectorSyntaxError` feedback 을 dot+colon 공통 규칙으로 확장했다. `NotImplementedError` feedback 에도 pseudo-element 안내를 유지하면서 soupsieve 의 `Pseudo-class ':<name>'` 오류가 Tailwind colon-variant 미escape 또는 class 점 누락일 수 있다고 알려준다.
- 회귀 test: `tests/validate/test_selector_compile.py` 에 dot escape feedback 강화와 `a:aspect-w-1` colon-variant feedback 재현 케이스를 추가했다.

## Track B 6-layer audit

- E: hit — schema validation 단계가 selector compile 실패를 register retry feedback 으로 돌려줄 수 있다. 기존 compile gate 를 유지하고 메시지만 더 구체화했다.
- D: hit — 실패 실행 결과(`SelectorSyntaxError`, `NotImplementedError`)를 agent retry 가 고칠 수 있는 recipe 로 바꾸는 자리다.
- C: miss — probe digest 가 새 데이터를 더 뽑아야 알 수 있는 문제가 아니다. selector 문자열 자체에서 컴파일 실패가 드러난다.
- B: miss — few-shot config 추가보다 validator feedback 과 system rule 이 직접 원인에 가깝다.
- A: hit — config_writer 가 처음 selector 를 쓸 때 Tailwind escape 를 알고 있어야 같은 retry 낭비를 줄인다.
- F: miss — 새 strategy, adapter, recognizer, register flow 변경이 필요 없다.

## 영향과 남은 리스크

영향 표면은 CSS selector 문자열 validation 과 config_writer prompt 다. 기존 정상 selector 의 컴파일 결과는 바꾸지 않고, 실패 메시지에 retry 가능한 escape 예시만 추가했다.

아직 일반화하지 않은 범위: Tailwind arbitrary value 나 CSS 특수문자 전체(`[` `]` `(` `)` `,` `/`) 자동 escape 는 다루지 않았다. 기존 prompt 는 그런 class 를 가능하면 빼고 stable class/tag 조합을 쓰라고 지시한다. 이번 lift 는 점과 colon utility escape 에 한정한다.

## 검증

- `PYTHONPATH=. python tests/validate/test_selector_compile.py` — PASS 7/7.
- `python scripts/probe_smoke.py --stage 3 --stage 5` — PASS 1642 / FAIL 0 / WARN 1 (`test_worker_failure_routing` protocol warning).
- `python scripts/vocab_lint.py` — FAIL 5 existing avoid-term hits in `.claude/skills/hand-config/SKILL.md` and older case files. This change did not add new vocab lint hits.

`docs/cases/INDEX.md` / `output/cases.sqlite3` backfill 은 hard-stop 지시에 따라 실행하지 않았다.
