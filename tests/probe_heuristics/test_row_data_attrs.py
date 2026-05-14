"""probe.extract._row_data_attrs — 행 요소·내부 첫 <a> 의 data-* 속성 수집."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from bs4 import BeautifulSoup
    from probe.extract import _row_data_attrs

    cases: list[tuple[str, bool, str]] = []

    def find_li(html: str):
        return BeautifulSoup(html, "lxml").find("li")

    # 1. li 에 data-* 만 (자식 a 없음)
    li = find_li('<li data-id="12345" data-no="9999">x</li>')
    out = _row_data_attrs(li)
    cases.append(("li_only", out == {"data-id": "12345", "data-no": "9999"}, f"got {out!r}"))

    # 2. li 에 data-id + 자식 a 에 data-threadid (둘 다 수집)
    li = find_li('<li data-id="1"><a data-threadid="99" href="javascript:go(99)">t</a></li>')
    out = _row_data_attrs(li)
    cases.append(("li_and_a_data", out == {"data-id": "1", "data-threadid": "99"},
                  f"got {out!r}"))

    # 3. data-* 없음 → 빈 dict
    li = find_li('<li class="item"><a href="/view/1">t</a></li>')
    out = _row_data_attrs(li)
    cases.append(("no_data_attrs", out == {}, f"got {out!r}"))

    # 4. value 80자 자르기
    long_val = "a" * 200
    li = find_li(f'<li data-x="{long_val}">x</li>')
    out = _row_data_attrs(li)
    cases.append(("value_truncated_80", len(out.get("data-x", "")) == 80, f"got len={len(out.get('data-x',''))}"))

    # 5. max_attrs 한도
    attrs = " ".join(f'data-k{i}="{i}"' for i in range(12))
    li = find_li(f'<li {attrs}>x</li>')
    out = _row_data_attrs(li, max_attrs=3)
    cases.append(("max_attrs_limited", len(out) == 3, f"got len={len(out)}"))

    # 6. data-* 아닌 속성 제외
    li = find_li('<li id="x" class="row" data-id="42">x</li>')
    out = _row_data_attrs(li)
    cases.append(("non_data_excluded", out == {"data-id": "42"}, f"got {out!r}"))

    return cases
