"""probe.hydration.extract_inline_data — JSON island / js_array / js_push 후보."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from probe.hydration import extract_inline_data

    cases: list[tuple[str, bool, str]] = []

    # 1. JSON island (application/json)
    html = (
        '<script type="application/json" id="data">'
        '{"items": [' + ",".join(f'{{"id":{i},"title":"t{i}"}}' for i in range(6)) + ']}'
        '</script>'
    )
    out = extract_inline_data(html)
    json_island = [c for c in out if c.get("kind") == "json_island"]
    cases.append(("json_island_detected", len(json_island) >= 1, f"got out={out!r}"))

    # 2. js_array — `var X = [ {...}, ... ]`
    html = 'var notices = [' + ",".join(f'{{"id":{i},"title":"t{i}"}}' for i in range(6)) + '];'
    out = extract_inline_data(html)
    js_arr = [c for c in out if c.get("kind") == "js_array"]
    cases.append(("js_array_detected", len(js_arr) >= 1, f"got out={out!r}"))
    if js_arr:
        cases.append(("js_array_var_name", js_arr[0].get("var") == "notices",
                      f"got {js_arr[0]!r}"))

    # 3. js_push — X.push({...}) 3회+
    html = ''.join(
        f'articles.push({{"dataid":{i},"title":"t{i}"}});' for i in range(5)
    )
    out = extract_inline_data(html)
    pushes = [c for c in out if c.get("kind") == "js_push"]
    cases.append(("js_push_detected", len(pushes) >= 1, f"got out={out!r}"))
    if pushes:
        cases.append(("js_push_var_name", pushes[0].get("var") == "articles",
                      f"got {pushes[0]!r}"))

    # 4. js_push 광고 큐 (dataLayer) 제외
    html = ''.join(f'dataLayer.push({{"event":"e{i}"}});' for i in range(5))
    out = extract_inline_data(html)
    pushes = [c for c in out if c.get("kind") == "js_push" and c.get("var") == "dataLayer"]
    cases.append(("dataLayer_excluded", len(pushes) == 0, f"got out={out!r}"))

    # 5. 빈 HTML
    cases.append(("empty_html", extract_inline_data("") == [], ""))

    return cases
