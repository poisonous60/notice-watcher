"""probe.extract._signature — Tag → 'name.class1.class2' 시그니처 (반복 패턴 그룹핑 키)."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from bs4 import BeautifulSoup
    from probe.extract import _signature

    cases: list[tuple[str, bool, str]] = []

    li1 = BeautifulSoup('<li class="item active">x</li>', "lxml").find("li")
    out = _signature(li1)
    cases.append(("li_two_classes", out == "li.item.active", f"got {out!r}"))

    li2 = BeautifulSoup('<li>x</li>', "lxml").find("li")
    out = _signature(li2)
    cases.append(("li_no_class", out == "li", f"got {out!r}"))

    div = BeautifulSoup('<div class="row"><span>y</span></div>', "lxml").find("div")
    out = _signature(div)
    cases.append(("div_one_class", out == "div.row", f"got {out!r}"))

    return cases
