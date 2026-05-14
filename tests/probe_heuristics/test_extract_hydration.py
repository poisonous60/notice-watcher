"""probe.hydration.extract_hydration — __NEXT_DATA__/__NUXT__/__INITIAL_STATE__ 추출."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from probe.hydration import extract_hydration

    cases: list[tuple[str, bool, str]] = []

    # 1. __NEXT_DATA__
    html = '<html><body><script id="__NEXT_DATA__" type="application/json">{"props":{"x":1}}</script></body></html>'
    out = extract_hydration(html)
    cases.append(("next_data_parsed", out.get("__NEXT_DATA__") == {"props": {"x": 1}},
                  f"got {out!r}"))

    # 2. __NUXT__
    html = '<html><script>window.__NUXT__={"state":{"y":2}};</script></html>'
    out = extract_hydration(html)
    cases.append(("nuxt_parsed", out.get("__NUXT__") == {"state": {"y": 2}}, f"got {out!r}"))

    # 3. __INITIAL_STATE__
    html = '<script>window.__INITIAL_STATE__={"z":3};</script>'
    out = extract_hydration(html)
    cases.append(("initial_state_parsed", out.get("__INITIAL_STATE__") == {"z": 3}, f"got {out!r}"))

    # 4. 셋 다 동시
    html = ('<script id="__NEXT_DATA__" type="application/json">{"a":1}</script>'
            '<script>window.__NUXT__={"b":2};</script>'
            '<script>window.__INITIAL_STATE__={"c":3};</script>')
    out = extract_hydration(html)
    cases.append(("all_three", set(out.keys()) >= {"__NEXT_DATA__", "__NUXT__", "__INITIAL_STATE__"},
                  f"got keys {list(out.keys())}"))

    # 5. 빈/없음
    cases.append(("empty_html", extract_hydration("") == {}, ""))
    cases.append(("no_hydration", extract_hydration("<html><body>plain</body></html>") == {}, ""))

    # 6. 파싱 깨진 JSON → _parse_error 키
    html = '<script id="__NEXT_DATA__" type="application/json">{not json</script>'
    out = extract_hydration(html)
    cases.append(("malformed_next_data", isinstance(out.get("__NEXT_DATA__"), dict)
                  and "_parse_error" in (out.get("__NEXT_DATA__") or {}),
                  f"got {out!r}"))

    return cases
