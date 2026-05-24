"""config JSON 스키마 + 검증.

스키마는 의도적으로 느슨하게 둔다(포맷이 아직 진화 중). 형식 검증은 jsonschema 로,
값 수준 검증(transform 이름 존재, 정규식 컴파일, strategy 별 필수 키)은 `validate_config` 로.

config 한 개 = 게시판 한 개. 최상위 키:
  version      : int (현재 1)
  site         : str  (NoticePost.site)
  board        : str  (NoticePost.board, url_template 의 {board} 로도 쓰임)
  strategy     : "httpx_html" | "httpx_json" | "playwright_html" | "handwritten"
  headers      : dict[str,str]   (httpx_*/playwright_*)
  timeout      : number          (기본 15)
  proxy_url    : str|null        ("{target}" 자리에 URL-encoded 원본; httpx_* 만)
  polite_sleep : {min:number, max:number}  (선택; 엔진 기본값보다 *느릴 때만* 적용 = 하한)
  list         : { ... }
  article      : { ... }
  # strategy == "handwritten" 일 때:
  adapter      : str   (adapters 패키지의 클래스명)
  kwargs       : dict

list:
  url_template : "https://.../?id={board}"   ({board},{page},{page_size} 치환)
  pagination   : {kind:"query_param"|"offset"|"none", page_param?, size_param?,
                  offset_param?, page_unit?(int), extra_params_when_paged?:dict}
  page_size_max: int (선택; 서버가 page_size 를 cap 하는 경우)
  tls_fallback : "playwright" | "none" (선택; httpx TLS handshake 실패 시 playwright_html 로 재생성 힌트)
  # --- httpx_html / playwright_html ---
  row_selector : "tr.ub-content"
  exclude_selector : "..."        (선택; 이 selector 에 매칭되는 행 제거)
  include_notices  : bool         (기본 true)
  notice_class_absent : "us-post" (선택; include_notices==false 일 때 이 class 없는 행을 공지로 보고 제거)
  wait_selector : "..."           (playwright_html 전용; 이 요소가 나타날 때까지 대기)
  # --- httpx_json ---
  list_path    : ["data","list"]  (목록 배열까지의 JSON 경로)
  item_path    : ["item"]         (선택; 각 엔트리 안에서 item dict 위치)
  type_field   : "type"           (선택)
  type_allow   : ["ARTICLE"]      (선택; type_field 값이 이 안에 있어야 채택)
  success_when : {path:["code"], equals:0}  (선택; payload 수준 성공 체크)
  # --- 공통 ---
  fields       : { post_id:[...], title:[...], url:[...], published_at:[...],
                   author:[...], category:[...], summary:[...], cover_image:[...] }
                 각 값은 source dict 의 리스트(fallback chain). source 형식은 extract_helpers 참고.

article:
  url_template : "https://.../api/bulletin/{post_id}"  (선택; 없으면 post.url 사용)
  fetch_kind   : "html" | "json"   (기본: list strategy 계열)
  skip_status  : [401,403]         (선택; 이 상태면 본문 비워서 반환)
  success_when : {...}             (json 전용; 선택)
  data_path    : ["data"]          (json 전용; 본문 객체까지의 경로. content/enrich 는 이 기준 상대 경로)
  content      : [ {from:"css", selector:"div.fr-view", html:true} ]  또는 [ {from:"json", path:["data"]} ]
  enrich       : { title:[...], published_at:[...], author:[...], ... }  (선택; None 인 기존 값만 덮어씀)
  body_empty_acceptable : bool     (선택; True 면 generate/validate 의 article_body_len 체크가 hard=False 로 완화 —
                                    본문이 본질적으로 없는 사이트(검색결과 SERP, 게임 디렉토리, 외부 host 행 aggregator 등)
                                    에서 자동 등록을 통과시키기 위함. 봇은 baseline 후 body_empty_at_baseline=true 면
                                    "본문 추출 안 됨" 경고를 자동으로 메시지에 붙임 — 사용자 향 경고는 그대로 작동.)
"""
from __future__ import annotations

import re
from typing import Any, Optional

from .transforms import TRANSFORMS


# 느슨한 JSON Schema (형식 골격만 검사).
CONFIG_JSON_SCHEMA: dict = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["version", "site", "board", "strategy"],
    "properties": {
        "version": {"type": "integer"},
        "site": {"type": "string", "minLength": 1},
        "board": {"type": "string"},
        "strategy": {"enum": ["httpx_html", "httpx_json", "playwright_html", "handwritten"]},
        "headers": {"type": "object"},
        "timeout": {"type": "number"},
        "encoding": {"type": "string"},
        "proxy_url": {"type": ["string", "null"]},
        "polite_sleep": {
            "type": "object",
            "properties": {"min": {"type": "number"}, "max": {"type": "number"}},
        },
        "adapter": {"type": "string"},
        "kwargs": {"type": "object"},
        "storage_state_path": {"type": "string"},
        "headless": {"type": "boolean"},
        "nav_timeout_ms": {"type": "integer"},
        "idle_timeout_ms": {"type": "integer"},
        "list": {
            "type": "object",
            "properties": {
                "url_template": {"type": "string"},
                "pagination": {"type": "object"},
                "page_size_max": {"type": "integer"},
                "row_selector": {"type": "string"},
                "row_required_selector": {"type": "string"},
                "exclude_selector": {"type": "string"},
                "include_notices": {"type": "boolean"},
                "notice_class_absent": {"type": "string"},
                "wait_selector": {"type": "string"},
                "list_path": {"type": "array"},
                "item_path": {"type": "array"},
                "type_field": {"type": "string"},
                "type_allow": {"type": "array"},
                "success_when": {"type": "object"},
                "script_root": {"type": "object"},
                "tls_fallback": {"enum": ["playwright", "none"]},
                "fields": {"type": "object"},
            },
        },
        "article": {
            "type": "object",
            "properties": {
                "url_template": {"type": "string"},
                "fetch_kind": {"enum": ["html", "json"]},
                "skip_status": {"type": "array", "items": {"type": "integer"}},
                "success_when": {"type": "object"},
                "data_path": {"type": "array"},
                "content": {"type": "array"},
                "enrich": {"type": "object"},
                "re_extract": {"type": "boolean"},
                "body_empty_acceptable": {"type": "boolean"},
            },
        },
    },
}

_STANDARD_FIELDS = {
    "post_id", "title", "url", "published_at", "author", "category", "summary", "cover_image",
}

_SOURCE_KINDS = {"css", "attr", "json", "const", "template", "concat", "class_present"}


class ConfigError(ValueError):
    """config 가 스키마/값 검증에 실패."""


def _jsonschema_validate(cfg: dict) -> list[str]:
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return []  # jsonschema 미설치 시 형식 검사는 건너뜀(값 검사는 그대로 수행)
    errs: list[str] = []
    validator = jsonschema.Draft7Validator(CONFIG_JSON_SCHEMA)
    for e in validator.iter_errors(cfg):
        loc = "/".join(str(p) for p in e.path)
        errs.append(f"[schema:{loc or '<root>'}] {e.message}")
    return errs


def _check_transform_chain(chain: Any, where: str, errs: list[str]) -> None:
    if chain is None:
        return
    if not isinstance(chain, list):
        errs.append(f"{where}: transform 은 리스트여야 함")
        return
    for i, step in enumerate(chain):
        if not isinstance(step, list) or not step or not isinstance(step[0], str):
            errs.append(f"{where}[{i}]: transform step 은 [\"name\", args...] 형식이어야 함")
            continue
        name = step[0]
        if name not in TRANSFORMS:
            errs.append(f"{where}[{i}]: 알 수 없는 transform {name!r} (허용: {sorted(TRANSFORMS)})")
        if name == "regex_extract" and len(step) >= 2 and isinstance(step[1], str):
            try:
                re.compile(step[1])
            except re.error as ex:
                errs.append(f"{where}[{i}]: regex_extract 패턴 컴파일 실패: {ex}")


def _check_css_selector(sel: Any, where: str, errs: list[str]) -> None:
    """CSS 선택자가 엔진의 매처(bs4 `.select` = soupsieve)로 컴파일되는지 검증.
    런타임 `soupsieve.SelectorSyntaxError`(예: LLM 이 Tailwind 클래스 `space-y-1.5` 의 점을
    미escape → `.5` 가 잘못된 클래스) 가 fetch_list 도중 크래시(rc=1)나는 걸 config 검증 시점에
    선반영 — register.py retry feedback 로 회수. soupsieve 미설치 시 skip (jsonschema 와 동일)."""
    if not isinstance(sel, str):
        return
    s = sel.strip()
    if not s or s == ":self":  # 생략/:self → 행 요소 자체 (선택자 아님)
        return
    try:
        import soupsieve  # type: ignore
    except ImportError:
        return
    try:
        soupsieve.compile(s)
    except soupsieve.SelectorSyntaxError as ex:
        first = str(ex).splitlines()[0] if str(ex) else ex.__class__.__name__
        errs.append(f"{where}: CSS 선택자 컴파일 실패 — {first}. "
                    f"Tailwind 숫자 클래스(`space-y-1.5`)의 점은 `\\.` escape 필요 (예: `space-y-1\\.5`). 선택자={s!r}")


_ALWAYS_CONTEXT = {"site", "board"}  # extract_row 가 항상 context 에 넣는 키


def _check_source(src: Any, where: str, errs: list[str], available_fields: Optional[set] = None) -> None:
    avail = available_fields if available_fields is not None else set()
    if "const" in src and "from" not in src:  # concat 의 part 형태
        return
    if "field" in src and "from" not in src:  # concat 의 part: 다른 필드 참조
        ref = src["field"]
        if ref not in avail and ref not in _ALWAYS_CONTEXT:
            errs.append(f"{where}: concat 이 아직 추출되지 않은 필드 {ref!r} 를 참조 — fields 에서 {ref!r} 를 더 앞에 선언하거나(또는 site/board) 다른 source 사용")
        return
    kind = src.get("from")
    if kind not in _SOURCE_KINDS:
        errs.append(f"{where}: source 'from' 이 {sorted(_SOURCE_KINDS)} 중 하나가 아님: {kind!r}")
        return
    if kind in ("css", "attr"):
        # selector 생략 / ":self" → 행 요소 자체. 그 외 빈 값은 잘못.
        sel = src.get("selector")
        if sel is not None and not isinstance(sel, str):
            errs.append(f"{where}: selector 는 문자열이거나 생략(=행 자체)이어야 함")
        else:
            _check_css_selector(sel, f"{where}.selector", errs)
        if kind == "attr" and not src.get("attr"):
            errs.append(f"{where}: attr source 는 'attr' 필요")
        if src.get("pick") == "first_matching" and not src.get("match"):
            errs.append(f"{where}: pick=first_matching 은 'match' 필요")
        for key in ("match",):
            if isinstance(src.get(key), str):
                try:
                    re.compile(src[key])
                except re.error as ex:
                    errs.append(f"{where}: '{key}' regex 컴파일 실패: {ex}")
    elif kind == "json":
        if not isinstance(src.get("path"), list):
            errs.append(f"{where}: json source 는 'path' 리스트 필요")
    elif kind == "template":
        if not isinstance(src.get("value"), str):
            errs.append(f"{where}: template source 는 문자열 'value' 필요")
    elif kind == "concat":
        if not isinstance(src.get("parts"), list) or not src["parts"]:
            errs.append(f"{where}: concat source 는 비어있지 않은 'parts' 필요")
        else:
            for j, part in enumerate(src["parts"]):
                if not isinstance(part, dict):
                    errs.append(f"{where}.parts[{j}]: dict 여야 함")
                else:
                    _check_source(part, f"{where}.parts[{j}]", errs, available_fields=avail)
    elif kind == "class_present":
        if not src.get("class"):
            errs.append(f"{where}: class_present source 는 'class' 필요")
    _check_transform_chain(src.get("transform"), f"{where}.transform", errs)


def _check_fields(fields: Any, where: str, errs: list[str]) -> None:
    if not isinstance(fields, dict):
        errs.append(f"{where}: fields 는 객체여야 함")
        return
    declared: set = set()  # 지금까지 선언된 필드명 (concat 의 {field:..} 참조 검증용 — 선언 순서 기준)
    for name, spec in fields.items():
        speclist = spec if isinstance(spec, list) else [spec]
        if not speclist:
            errs.append(f"{where}.{name}: 비어있는 fallback chain")
        for i, src in enumerate(speclist):
            if not isinstance(src, dict):
                errs.append(f"{where}.{name}[{i}]: source 는 dict 여야 함")
            else:
                _check_source(src, f"{where}.{name}[{i}]", errs, available_fields=declared)
        declared.add(name)


def validate_config(cfg: dict) -> None:
    """검증 실패 시 ConfigError(모든 메시지 합침) 발생."""
    errs: list[str] = []
    errs.extend(_jsonschema_validate(cfg))

    strategy = cfg.get("strategy")
    if strategy == "handwritten":
        if not cfg.get("adapter"):
            errs.append("handwritten strategy 는 'adapter'(클래스명) 필요")
    elif strategy in ("httpx_html", "httpx_json", "playwright_html"):
        lst = cfg.get("list")
        if not isinstance(lst, dict):
            errs.append("'list' 객체 필요")
        else:
            if not lst.get("url_template"):
                errs.append("list.url_template 필요")
            fields = lst.get("fields")
            if not isinstance(fields, dict):
                errs.append("list.fields 객체 필요")
            else:
                if "post_id" not in fields:
                    errs.append("list.fields 에 'post_id' 필수(새 글 감지 키)")
                if "title" not in fields:
                    errs.append("list.fields 에 'title' 필수")
                _check_fields(fields, "list.fields", errs)
            if strategy in ("httpx_html", "playwright_html") and not lst.get("row_selector"):
                errs.append("httpx_html/playwright_html 은 list.row_selector 필요")
            # top-level list 선택자 컴파일 검증 (field source 아닌 selector — _check_source 미경유).
            for _sk in ("row_selector", "row_required_selector", "exclude_selector", "wait_selector"):
                _check_css_selector(lst.get(_sk), f"list.{_sk}", errs)
            if strategy == "httpx_json" and not isinstance(lst.get("list_path"), list):
                errs.append("httpx_json 은 list.list_path(리스트) 필요")
            pag = lst.get("pagination")
            if pag is not None:
                if pag.get("kind") not in ("query_param", "offset", "none", None):
                    errs.append(f"list.pagination.kind 가 이상함: {pag.get('kind')!r}")
        art = cfg.get("article")
        if art is not None:
            if "content" in art:
                content_val = art["content"]
                body_optional = bool(art.get("body_empty_acceptable"))
                if not (body_optional and isinstance(content_val, list) and not content_val):
                    _check_fields({"content": content_val}, "article", errs)
            if "enrich" in art:
                _check_fields(art["enrich"], "article.enrich", errs)
    else:
        errs.append(f"알 수 없는 strategy: {strategy!r}")

    if errs:
        raise ConfigError("config 검증 실패:\n  - " + "\n  - ".join(errs))


def is_valid(cfg: dict) -> bool:
    try:
        validate_config(cfg)
        return True
    except ConfigError:
        return False
