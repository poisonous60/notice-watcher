---
slug: _generic_pseudo_element_selector_reject
url: (cross-site / trigger: https://whirlpool.co.jp/news/)
status: 🧱 영구 게이트 — pseudo-element selector 거부 (validator)
outcome: improved
date: 2026-05-26
fix_layer: E
failure_keys: [css_selector_compile, soupsieve_pseudo_element, validator_gate]
tags: [validator, css-selector, soupsieve, schema, games-indie-studios-asia]
requested_by: hand-config-batch-2026-05-24-games-indie-studios-asia
---

## 트리거

`https://whirlpool.co.jp/news/` 자동 등록 batch 시도가 `register.py` 도중 traceback 으로 BUG:

```
File ".venv/lib/python3.13/site-packages/soupsieve/css_parser.py", line 998, in parse_selectors
    raise NotImplementedError(f"Pseudo-element found at position {m.start(0)}")
NotImplementedError: Pseudo-element found at position 8
```

= LLM 이 생성한 config 의 selector 에 `::before`/`::after`/`::first-line` 류 pseudo-element 포함. soupsieve(bs4 `.select`) 가 컴파일 단계에서 `NotImplementedError` raise — DOM 노드 매칭 엔진이라 pseudo-element 미지원.

## 진단

기존 게이트 `engine/config_schema.py:_check_css_selector` 는 `soupsieve.SelectorSyntaxError` 만 잡음 (Tailwind 숫자 클래스 `.5` 미escape 케이스 — etoland 2026-05-21-forums). `NotImplementedError` 는 다른 예외 hierarchy 라 통과 → fetch_list 도중 크래시 = `.BUG.json` 또는 raw traceback 큐 진입.

분류기 위치 (E/D/C/B/A/F 중): **E (schema validator)**. config 검증 시점에 거부하고 retry feedback 으로 LLM 회수 — runtime 크래시 없음.

## 무엇을 바꿨나

`engine/config_schema.py:_check_css_selector` 의 `try/except` 에 `except NotImplementedError` 추가:

```python
except NotImplementedError as ex:
    first = str(ex).splitlines()[0] if str(ex) else ex.__class__.__name__
    errs.append(f"{where}: CSS 선택자 컴파일 실패 — {first}. "
                f"soupsieve(bs4 `.select`)는 pseudo-element(`::before`/`::after`/`::first-line` 등)를 "
                f"지원하지 않음 — 엔진은 DOM 노드만 매칭하므로 pseudo-element 제거 또는 "
                f"일반 자식 selector 로 대체 필요. 선택자={s!r}")
```

retry feedback 으로 LLM 이 다음 attempt 에서 pseudo-element 제거 가능. fail_taxonomy 별 Subkind 불필요 — 기존 dynamic `[FAIL]:CSS 선택자 컴파일 실패` 가 capture.

## 회귀 검증

- `tests/validate/test_selector_compile.py` — `pseudo_element_rejected` 케이스 추가:
  - `div::before` row_selector → ConfigError raise + msg 에 "pseudo-element" 포함.
  - 기존 5 케이스 (valid/malformed/escaped/self/field) 통과 유지.
  - 총 6 PASS.
- `python scripts/probe_smoke.py --stage 3 --stage 5` exit 0. 267/267 configs validate (회귀 0).

## 일반화 후보

이 fix 자체가 일반화 후보의 적용. 미래 LLM 이 같은 실수 (pseudo-element 박기) 해도 validate 단계 거부 + retry feedback 회수.

## 후속

- batch retry 후 whirlpool 회수 가능성 (LLM 이 pseudo-element 제거 후 재시도). 실패해도 cap_blocked / gate_reject 등 다른 종결 상태로 정리.
