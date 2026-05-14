"""probe.extract._walk_long_strings — JSON 안 본문스러운 긴 문자열 수집."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import _walk_long_strings

    cases: list[tuple[str, bool, str]] = []

    # 1. ≥200자 문자열 → 키 무관 수집
    long_text = "x" * 250
    out: list = []
    _walk_long_strings({"foo": long_text}, [], out)
    paths = [tuple(h["path"]) for h in out]
    cases.append(("long_str_picked", ("foo",) in paths, f"got paths={paths!r}"))

    # 2. body-key 힌트 + ≥60자 → 짧아도 수집
    out = []
    _walk_long_strings({"content": "a" * 80}, [], out)
    cases.append(("body_key_hint_60", any(h["key_hit"] and h["key"] == "content" for h in out),
                  f"got {out!r}"))

    # 3. HTMLish 마크업 + ≥60자
    out = []
    _walk_long_strings({"x": "<p>hello</p>" + "a" * 60}, [], out)
    cases.append(("htmlish_60", any(h["html"] for h in out), f"got {out!r}"))

    # 4. 50자 일반 키 — 수집 안 됨
    out = []
    _walk_long_strings({"x": "short text under sixty chars but no hint"}, [], out)
    cases.append(("short_no_hint_skipped", out == [], f"got {out!r}"))

    # 5. nested path 추적
    out = []
    _walk_long_strings({"a": {"b": {"contentHtml": "h" * 100}}}, [], out)
    paths = [tuple(h["path"]) for h in out]
    cases.append(("nested_path", ("a", "b", "contentHtml") in paths, f"got paths={paths!r}"))

    # 6. list index path 추적
    out = []
    _walk_long_strings([{"body": "z" * 100}], [], out)
    paths = [tuple(h["path"]) for h in out]
    cases.append(("list_index_path", (0, "body") in paths, f"got paths={paths!r}"))

    # 7. max_depth — 깊으면 안 들어감
    deeply = {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"body": "z" * 100}}}}}}}}}
    out = []
    _walk_long_strings(deeply, [], out, max_depth=3)
    cases.append(("max_depth_cut", out == [], f"got {len(out)} hits at depth>3"))

    # 8. budget 한계 — 폭주 방지
    big = {f"k{i}": {"nested": "x" * 100} for i in range(100)}
    out = []
    budget = [10]
    _walk_long_strings(big, [], out, budget=budget)
    cases.append(("budget_limited", budget[0] <= 0, f"budget remaining={budget[0]}"))

    return cases
