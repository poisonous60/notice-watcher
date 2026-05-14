"""probe.hydration._balanced — 짝 맞는 괄호 슬라이스 (문자열 리터럴 안 무시)."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from probe.hydration import _balanced

    cases: list[tuple[str, bool, str]] = []

    # 1. typical {}
    s = '{"a": 1, "b": [1, 2]}'
    out = _balanced(s, 0, "{", "}")
    cases.append(("simple_brace", out is not None and out[0] == s, f"got {out!r}"))

    # 2. nested
    s = '[ {"x": 1}, {"y": 2} ]'
    out = _balanced(s, 0, "[", "]")
    cases.append(("nested_array", out is not None and out[0] == s, f"got {out!r}"))

    # 3. 문자열 리터럴 안 `]` 무시
    s = '[ "a]b]c", "d]" ]'
    out = _balanced(s, 0, "[", "]")
    cases.append(("ignore_bracket_in_string", out is not None and out[0] == s, f"got {out!r}"))

    # 4. 짝 없음
    s = '[ 1, 2'
    out = _balanced(s, 0, "[", "]")
    cases.append(("unbalanced_returns_none", out is None, f"got {out!r}"))

    # 5. start 가 open 이 아니면 0 depth 에서 끝남
    s = 'x {} y'
    out = _balanced(s, 2, "{", "}")
    cases.append(("offset_start", out is not None and out[0] == "{}", f"got {out!r}"))

    # 6. 이스케이프된 따옴표 안 괄호 무시
    s = r'[ "a\"]b" ]'
    out = _balanced(s, 0, "[", "]")
    cases.append(("escaped_quote", out is not None and out[0] == s, f"got {out!r}"))

    return cases
