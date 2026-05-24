"""α minimal — MDR `list_candidates` 알고리즘 port (measurement-only).

scrapinghub/mdr 의 `list_candidates` 만 Py3 port (3 line patch from Py2 original:
`cStringIO` → `io.BytesIO`, `unicode` 체크 drop, `iteritems` → `items`).

본 helper 는 digest 의 *별 field* (`mdr_candidates`) 에만 박힘. config_writer prompt
에는 *통과시키지 않는다* — 2026-05-24 codex review 결론: wrong-block 후보가 prompt
오염할 위험이 있어 measurement-only 로만 운영 (`docs/2026-05-24-layer-addition-plan.md`).

References:
- 원본 알고리즘: `experiments/prior-art-bench/_libs/mdr/mdr/mdr.py:68-94` (Py2)
- 첫 port: `experiments/prior-art-bench/tools/mdr_list_candidates_py3.py`
"""
from __future__ import annotations

import collections
import operator
import re
from io import BytesIO

from lxml import etree


def _common_prefix(*sequences):
    if not sequences:
        return []
    out = []
    for parts in zip(*sequences):
        if all(p == parts[0] for p in parts):
            out.append(parts[0])
        else:
            break
    return out


def _simplify_xpath(xpath: str) -> str:
    return re.sub(r"\[\d+\]", "", xpath)


# measurement-only 가 build_digest 막지 않게 입력 hard cap. 큰 HTML 에서 xpath 인덱싱이
# O(N) 메모리 (text-node 마다 부모 xpath 저장) — adversarial 입력 시 OOM 가능. 2026-05-24 codex
# 2차 리뷰 MED.
_INPUT_MAX_BYTES = 500_000
_TEXT_NODE_BUDGET = 20_000


def mdr_candidate_xpaths(html: bytes | str, *, top_k: int = 10,
                         encoding: str = "utf8") -> list[dict]:
    """MDR list_candidates 결과 → 상위 K 개 candidate xpath + 자식 row 수.

    Returns: list of {"xpath": str, "child_count": int, "row_with_link": int}.
    Empty list on parse error (fail-soft — measurement layer).
    """
    if not html:
        return []
    if isinstance(html, str):
        html = html.encode(encoding, errors="replace")
    if len(html) > _INPUT_MAX_BYTES:
        html = html[:_INPUT_MAX_BYTES]
    try:
        parser = etree.HTMLParser(encoding=encoding, recover=True)
        doc = etree.parse(BytesIO(html), parser)
    except (etree.XMLSyntaxError, UnicodeDecodeError):
        try:
            parser = etree.HTMLParser(recover=True)
            doc = etree.parse(BytesIO(html), parser)
        except Exception:
            return []

    d: dict[str, list[str]] = {}
    # text-node budget — adversarial 입력에서 dict 가 무한히 커지는 것 차단.
    seen = 0
    for e in doc.xpath('//*/text()[normalize-space()]'):
        p = e.getparent()
        if p is None:
            continue
        xpath = doc.getpath(p)
        d.setdefault(_simplify_xpath(xpath), []).append(xpath)
        seen += 1
        if seen >= _TEXT_NODE_BUDGET:
            break

    counter: collections.Counter = collections.Counter()
    for _key, elements in d.items():
        deepest = "/".join(_common_prefix(*[x.split('/') for x in elements]))
        if deepest:
            counter[deepest] += 1

    out: list[dict] = []
    for xp, _score in sorted(counter.items(), key=operator.itemgetter(1), reverse=True)[:top_k]:
        try:
            found = doc.xpath(xp)
        except etree.XPathEvalError:
            continue
        if not found:
            continue
        el = found[0]
        children = list(el)
        out.append({
            "xpath": xp,
            "child_count": len(children),
            "row_with_link": sum(1 for c in children if c.find(".//a") is not None),
        })
    return out
