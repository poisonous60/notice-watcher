"""strategy 공용 헬퍼: 목록 URL 빌드(페이지네이션), payload 성공 체크."""
from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl, quote

from ..extract_helpers import navigate_json


class _Safe(dict):
    def __missing__(self, key):  # noqa: D401
        return "{" + key + "}"


def render_template(template: str, **kwargs) -> str:
    """{name} 치환. 없는 placeholder 는 그대로 둠(format_map)."""
    return template.format_map(_Safe(**{k: ("" if v is None else v) for k, v in kwargs.items()}))


def render_url_template(template: str, *, board: str, page: int, page_size: int) -> str:
    return render_template(template, board=board, page=page, page_size=page_size)


def _set_query(url: str, updates: dict[str, str]) -> str:
    """url 의 query 에 updates 키들을 set/replace. updates 에 없는 키(중복 키 포함)는 순서·값 그대로 보존."""
    parts = urlsplit(url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    keys = set(updates)
    kept = [(k, v) for (k, v) in pairs if k not in keys]
    kept += [(k, str(v)) for k, v in updates.items()]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


def build_list_url(
    *,
    url_template: str,
    pagination: Optional[dict],
    board: str,
    page: int,
    page_size: int,
    page_size_max: Optional[int],
) -> tuple[str, int]:
    """(최종 URL, 실제 적용된 page_size) 반환.

    page_size_max 가 있으면 page_size 를 그 이하로 cap.
    """
    eff_ps = page_size
    if page_size_max is not None:
        eff_ps = min(page_size, int(page_size_max))

    url = render_url_template(url_template, board=board, page=page, page_size=eff_ps)

    pag = pagination or {}
    kind = pag.get("kind", "none")
    if kind == "none":
        return url, eff_ps

    updates: dict[str, str] = {}
    if kind == "query_param":
        # query_param 은 1페이지 포함 항상 page/size 파라미터를 붙인다.
        if pag.get("page_param"):
            updates[pag["page_param"]] = str(page)
        if pag.get("size_param"):
            updates[pag["size_param"]] = str(eff_ps)
    elif kind == "offset":
        # offset 은 2페이지부터만 offset/size 파라미터를 붙인다(1페이지는 깔끔한 기본 URL).
        if page > 1:
            unit = int(pag.get("page_unit", eff_ps))
            if pag.get("offset_param"):
                updates[pag["offset_param"]] = str((page - 1) * unit)
            if pag.get("size_param"):
                updates[pag["size_param"]] = str(unit)
    # extra_params_when_paged: kind 무관, page>1 일 때만 추가하는 쿼리 파라미터.
    if page > 1:
        for k, v in (pag.get("extra_params_when_paged") or {}).items():
            updates[k] = str(v)

    if updates:
        url = _set_query(url, updates)
    return url, eff_ps


def apply_proxy(url: str, proxy_url: Optional[str]) -> str:
    if not proxy_url:
        return url
    return proxy_url.replace("{target}", quote(url, safe=""))


def check_success(payload: Any, success_when: Optional[dict]) -> tuple[bool, str]:
    """success_when = {path:[...], equals: <값>}. None 이면 항상 성공."""
    if not success_when:
        return True, ""
    val = navigate_json(payload, success_when.get("path"))
    expected = success_when.get("equals")
    if "equals" in success_when:
        if val != expected:
            return False, f"success_when 실패: {success_when.get('path')} = {val!r} (기대값 {expected!r})"
    return True, ""
