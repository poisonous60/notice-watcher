"""config 의 field_map 추출 로직.

field spec = source dict 들의 리스트(fallback chain). 앞에서부터 시도해 None 이
아닌 첫 결과를 채택. 한 source 해석 중 예외가 나면 그 source 는 실패(None)로 보고
다음 fallback 으로 넘어간다(설정 버그성 예외는 validate_config 가 미리 잡는다).

source `from` 종류:
  css            : {from:"css", selector, attr?, html?, text?(기본 true), joiner?(" "),
                    pick?("first_matching"), match?(regex), transform?}
  attr           : css 와 동일하되 attr 필수 (의미상 별칭)
  json           : {from:"json", path:[키/인덱스...], transform?}
  const          : {from:"const", value: <임의값, null 가능>, transform?}
  template       : {from:"template", value:"...{board}...{post_id}...", transform?}  # context 로 .format
  concat         : {from:"concat", parts:[ {const:..} | {field:"name"} | <source dict> ... ]}
  class_present  : {from:"class_present", class:"us-post", negate?}  # html 행 전용 → "true"/"false"
"""
from __future__ import annotations

import re
from typing import Any, Optional

from bs4 import BeautifulSoup, Tag

from .transforms import apply_chain


# ---- 단일 source 해석 ----

def _classes(el: Tag) -> list[str]:
    c = el.get("class")
    if c is None:
        return []
    if isinstance(c, str):
        return c.split()
    return list(c)


def _el_value(el: Tag, source: dict) -> Any:
    attr = source.get("attr")
    if attr is not None:
        v = el.get(attr)
        if isinstance(v, (list, tuple)):
            return " ".join(str(x) for x in v)
        return v
    if source.get("html"):
        return str(el)
    # 기본: 텍스트
    joiner = source.get("joiner", " ")
    text_flag = source.get("text", True)
    if not text_flag:
        return str(el)
    return el.get_text(joiner, strip=True)


_SELF_SELECTORS = {None, "", ":self", ":scope", "self", "."}


def _resolve_css(root: Optional[Tag], source: dict) -> Any:
    if root is None:
        return None
    selector = source.get("selector")
    pick = source.get("pick")
    match = source.get("match")

    # selector 를 빼거나 ":self" 면 *행(root) 요소 자체* 를 가리킴 (반복 행이 곧 링크인 경우 등).
    if selector in _SELF_SELECTORS:
        val = _el_value(root, source)
        if match and (val is None or not re.search(match, str(val))):
            return None
        return val

    if pick == "first_matching":
        if not match:
            return None
        pat = re.compile(match)
        for el in root.select(selector):
            val = _el_value(el, source)
            if val is not None and pat.search(str(val)):
                return val
        return None

    el = root.select_one(selector)
    if el is None:
        return None
    val = _el_value(el, source)
    if match:
        if val is None or not re.search(match, str(val)):
            return None
    return val


def navigate_json(obj: Any, path: Optional[list]) -> Any:
    """JSON 경로(키/인덱스 리스트)를 따라 내려간다. 없으면 None."""
    cur = obj
    for key in path or []:
        if cur is None:
            return None
        if isinstance(key, int):
            if isinstance(cur, (list, tuple)) and -len(cur) <= key < len(cur):
                cur = cur[key]
            else:
                return None
        else:
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                return None
    return cur


def _resolve_json(item: Any, source: dict) -> Any:
    return navigate_json(item, source.get("path"))


def _resolve_template(source: dict, context: dict) -> Any:
    tmpl = source["value"]
    try:
        # context 값 중 None 은 빈 문자열 대신 실패 처리
        safe = {k: v for k, v in context.items() if v is not None}
        return tmpl.format(**safe)
    except (KeyError, IndexError, ValueError):
        return None


def _resolve_concat(root: Optional[Tag], item: Any, source: dict, context: dict) -> Any:
    parts_out: list[str] = []
    for part in source.get("parts", []):
        if not isinstance(part, dict):
            return None
        if "const" in part:
            parts_out.append(str(part["const"]))
            continue
        if "field" in part:
            v = context.get(part["field"])
            if v is None:
                return None
            parts_out.append(str(v))
            continue
        # 중첩 source
        v = _resolve_source(root, item, part, context)
        if v is None:
            return None
        parts_out.append(str(v))
    return "".join(parts_out)


def _resolve_class_present(root: Optional[Tag], source: dict) -> Any:
    if root is None:
        return None
    cls = source["class"]
    present = cls in _classes(root)
    if source.get("negate"):
        present = not present
    return "true" if present else "false"


def _resolve_source(root: Optional[Tag], item: Any, source: dict, context: dict) -> Any:
    kind = source.get("from")
    if kind in ("css", "attr"):
        raw = _resolve_css(root, source)
    elif kind == "json":
        raw = _resolve_json(item, source)
    elif kind == "const":
        raw = source.get("value")
    elif kind == "template":
        raw = _resolve_template(source, context)
    elif kind == "concat":
        raw = _resolve_concat(root, item, source, context)
    elif kind == "class_present":
        raw = _resolve_class_present(root, source)
    else:
        raise ValueError(f"unknown source 'from': {kind!r}")
    if raw is None:
        return None
    return apply_chain(raw, source.get("transform"))


def extract_field(
    spec: list[dict],
    *,
    root: Optional[Tag] = None,
    item: Any = None,
    context: Optional[dict] = None,
) -> Any:
    """fallback chain 을 앞에서부터 시도. None 이 아닌 첫 결과 반환. 전부 실패면 None."""
    ctx = context or {}
    for source in spec:
        try:
            v = _resolve_source(root, item, source, ctx)
        except Exception:
            v = None
        if v is not None:
            return v
    return None


def extract_row(
    *,
    root: Optional[Tag] = None,
    item: Any = None,
    fields_spec: dict[str, list],
    context_base: Optional[dict] = None,
) -> dict:
    """fields_spec(순서 보존 dict) 를 선언 순서대로 추출. 뒤 필드는 앞 필드를 context 로 참조 가능."""
    out: dict[str, Any] = {}
    ctx = dict(context_base or {})
    for name, spec in fields_spec.items():
        if isinstance(spec, dict):  # 단일 source 도 허용
            spec = [spec]
        v = extract_field(spec, root=root, item=item, context={**ctx, **out})
        out[name] = v
    return out


def parse_html(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", "lxml")


def parse_html_or_xml(text: str) -> BeautifulSoup:
    """`<?xml`/`<rss`/`<feed` prefix 면 XML parser, 아니면 HTML parser.

    RSS/Atom 응답을 lxml HTML parser 로 파싱하면 `<link>` `<guid>` 같은 HTML void
    element 가 self-closing 으로 처리돼 텍스트 내용 X (`it.find('link').get_text()` 빈
    문자열). XML parser (`lxml-xml`) 는 모든 tag 를 컨테이너로 처리 → content 정상 추출.

    catalog 의 RSS/Atom 사이트 (`bbs.ruliweb.com/.../rss`, `*.atom`, `*.xml` 등) 등록
    시 `parse_list_html` 가 호출. text 가 XML prefix 면 자동 분기.
    """
    head = (text or "").lstrip()[:64].lower()
    if head.startswith("<?xml") or head.startswith("<rss") or head.startswith("<feed"):
        return BeautifulSoup(text or "", "lxml-xml")
    return BeautifulSoup(text or "", "lxml")
