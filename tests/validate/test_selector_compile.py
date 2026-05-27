"""`engine.config_schema.validate_config` 의 CSS 선택자 컴파일 게이트 (fix-layer E).

LLM 이 Tailwind 숫자 클래스(`space-y-1.5`)의 점을 미escape → 엔진의 매처(bs4 `.select` =
soupsieve)가 fetch_list 도중 `SelectorSyntaxError` 크래시(rc=1). validate_config 시점에
선반영 → register.py retry feedback(escape 힌트)로 회수. etoland(2026-05-21-forums) 케이스.
"""
from __future__ import annotations


def _cfg(row_selector: str = "tr.item", title_selector: str = "a .subject") -> dict:
    return {
        "version": 1, "site": "x.example.com", "board": "b", "strategy": "httpx_html",
        "list": {
            "url_template": "https://x.example.com/",
            "row_selector": row_selector,
            "fields": {
                "post_id": [{"from": "attr", "selector": "a", "attr": "href"}],
                "title": [{"from": "css", "selector": title_selector, "text": True}],
            },
        },
    }


def run() -> list[tuple[str, bool, str]]:
    from engine.config_schema import validate_config, ConfigError
    cases: list[tuple[str, bool, str]] = []

    # 1) 정상 선택자 → 통과 (회귀 가드).
    try:
        validate_config(_cfg())
        cases.append(("valid_selector_passes", True, ""))
    except ConfigError as e:
        cases.append(("valid_selector_passes", False, str(e)))

    # 2) row_selector 의 미escape Tailwind 클래스(.5) → 거부 (etoland 재현).
    try:
        validate_config(_cfg(row_selector="main article ul.space-y-1.5 > li"))
        cases.append(("row_selector_malformed_rejected", False, "거부 안 됨"))
    except ConfigError as e:
        msg = str(e)
        ok = (
            "row_selector" in msg
            and "CSS 선택자 컴파일 실패" in msg
            and "escape" in msg
            and r".lg\:space-y-1\.5" in msg
        )
        cases.append(("row_selector_malformed_rejected", ok, msg.splitlines()[1] if "\n" in msg else msg))

    # 3) field source selector 의 미escape 클래스 → 거부 (_check_source 경유).
    try:
        validate_config(_cfg(title_selector="a .space-y-1.5"))
        cases.append(("field_selector_malformed_rejected", False, "거부 안 됨"))
    except ConfigError as e:
        cases.append(("field_selector_malformed_rejected",
                      "CSS 선택자 컴파일 실패" in str(e), str(e).splitlines()[-1][:120]))

    # 4) escape 된 형태(`space-y-1\.5`) → 통과 (LLM 이 retry 로 고친 형태).
    try:
        validate_config(_cfg(row_selector=r"main article ul.space-y-1\.5 > li"))
        cases.append(("escaped_selector_passes", True, ""))
    except ConfigError as e:
        cases.append(("escaped_selector_passes", False, str(e)))

    # 5) :self / 생략(=행 자체) → 컴파일 검증 skip (오거부 X).
    try:
        validate_config(_cfg(title_selector=":self"))
        cases.append(("self_selector_skipped", True, ""))
    except ConfigError as e:
        cases.append(("self_selector_skipped", False, str(e)))

    # 6) pseudo-element(`::before`/`::after`) → 거부 (whirlpool.co.jp/news/ 케이스).
    #    soupsieve.compile 이 SelectorSyntaxError 가 아닌 NotImplementedError 를 raise →
    #    이전 게이트는 통과해 fetch_list 도중 rc=1 크래시. validate 시점 차단.
    try:
        validate_config(_cfg(row_selector="div::before"))
        cases.append(("pseudo_element_rejected", False, "거부 안 됨"))
    except ConfigError as e:
        msg = str(e)
        ok = "CSS 선택자 컴파일 실패" in msg and "pseudo-element" in msg.lower()
        cases.append(("pseudo_element_rejected", ok, msg.splitlines()[1] if "\n" in msg else msg))

    # 7) Tailwind colon variant 를 leading pseudo-class 처럼 쓴 selector → escape 힌트 포함 거부 (outfit7 재현).
    try:
        validate_config(_cfg(row_selector="a:aspect-w-1"))
        cases.append(("tailwind_colon_variant_feedback", False, "거부 안 됨"))
    except ConfigError as e:
        msg = str(e)
        ok = (
            "CSS 선택자 컴파일 실패" in msg
            and "Tailwind" in msg
            and "colon-variant" in msg
            and r".lg\:flex" in msg
        )
        cases.append(("tailwind_colon_variant_feedback", ok, msg.splitlines()[1] if "\n" in msg else msg))

    return cases


if __name__ == "__main__":
    fail = 0
    for name, ok, msg in run():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  ({msg})")
        fail += 0 if ok else 1
    raise SystemExit(0 if fail == 0 else 1)
