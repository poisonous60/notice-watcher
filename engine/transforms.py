"""닫힌 transform 라이브러리.

config의 field_map에서 추출한 값(주로 str)을 정규화하는 변환 함수 모음.
LLM은 이 메뉴(`TRANSFORMS` 키)에서만 골라 쓴다. 임의 코드 금지.

config 표기: 각 transform 은 ["name", arg1, arg2, ...] 형태의 리스트.
  예) ["regex_extract", "[?&]no=(\\d+)"]
      ["urljoin", "https://gall.dcinside.com"]
      ["unixtime_to_iso", "Z", "s"]
chain = [[transform], [transform], ...] 순서대로 적용. 중간에 None 이 나오면 즉시 중단.
transform 이 예외를 던지면 그 chain 은 실패(None)로 본다 — 호출 측이 다음 fallback 으로 넘어간다.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Optional
from urllib.parse import urljoin as _urljoin


# ---- 개별 transform 구현 ----
# 규칙: 첫 인자는 항상 현재 값(value). value 가 None 이면 호출되지 않는다(apply_chain 이 short-circuit).

def _urljoin_t(value: str, base: str) -> str:
    return _urljoin(base, value)


def _strip_query_fragment(value: str) -> str:
    return value.split("?", 1)[0].split("#", 1)[0]


def _regex_extract(value: str, pattern: str, group: int = 1) -> Optional[str]:
    m = re.search(pattern, value)
    if not m:
        return None
    try:
        return m.group(group)
    except IndexError:
        return None


def _collapse_ws(value: str) -> str:
    return " ".join(value.split())


def _remove_prefix(value: str, prefix: str) -> str:
    return value[len(prefix):] if value.startswith(prefix) else value


def _strip_brackets(value: str) -> str:
    v = value.strip()
    if len(v) >= 2 and v[0] == "[" and v[-1] == "]":
        return v[1:-1].strip()
    return v


def _replace(value: str, old: str, new: str) -> str:
    return value.replace(old, new)


def _append(value: str, suffix: str) -> str:
    return f"{value}{suffix}"


def _prepend(value: str, prefix: str) -> str:
    return f"{prefix}{value}"


def _strip(value: str) -> str:
    return value.strip()


def _to_str(value: Any) -> str:
    return str(value)


def _lower(value: str) -> str:
    return value.lower()


def _upper(value: str) -> str:
    return value.upper()


def _zero_pad(value: str, width: int) -> str:
    return str(value).zfill(int(width))


def _parse_tz(tz: str) -> timezone:
    """'Z' / '+09:00' / '-05:30' / '+0900' → timezone."""
    if tz in ("Z", "z", "UTC", "utc", "+00:00", "+0000"):
        return timezone.utc
    sign = 1
    s = tz
    if s[0] in "+-":
        sign = -1 if s[0] == "-" else 1
        s = s[1:]
    s = s.replace(":", "")
    hh = int(s[0:2])
    mm = int(s[2:4]) if len(s) >= 4 else 0
    return timezone(sign * timedelta(hours=hh, minutes=mm))


def _iso8601(value: str, formats: list[str], tz: Optional[str] = None) -> Optional[str]:
    v = value.strip()
    for fmt in formats:
        try:
            dt = datetime.strptime(v, fmt)
        except ValueError:
            continue
        if dt.tzinfo is None and tz is not None:
            dt = dt.replace(tzinfo=_parse_tz(tz))
        return dt.isoformat()
    return None


def _date_only_to_iso(value: str, tz: str = "+09:00") -> str:
    """'YYYY-MM-DD' → 'YYYY-MM-DDT00:00:00+09:00'."""
    d = value.strip()
    return f"{d}T00:00:00{tz}"


def _unixtime_to_iso(value: Any, tz: str = "Z", unit: str = "s") -> Optional[str]:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if unit == "ms":
        n = n / 1000.0
    try:
        return datetime.fromtimestamp(n, tz=_parse_tz(tz)).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _default(value: Any, fallback: Any) -> Any:
    """value 가 None/'' 이면 fallback 으로 대체. (fallback chain 으로도 되지만 단축형.)"""
    if value is None or value == "":
        return fallback
    return value


# ---- 레지스트리 ----

TRANSFORMS: dict[str, Callable[..., Any]] = {
    "urljoin": _urljoin_t,
    "strip_query_fragment": _strip_query_fragment,
    "regex_extract": _regex_extract,
    "collapse_ws": _collapse_ws,
    "remove_prefix": _remove_prefix,
    "strip_brackets": _strip_brackets,
    "replace": _replace,
    "append": _append,
    "prepend": _prepend,
    "strip": _strip,
    "to_str": _to_str,
    "lower": _lower,
    "upper": _upper,
    "zero_pad": _zero_pad,
    "iso8601": _iso8601,
    "date_only_to_iso": _date_only_to_iso,
    "unixtime_to_iso": _unixtime_to_iso,
    "default": _default,
}


class UnknownTransform(ValueError):
    pass


def apply_one(value: Any, step: list) -> Any:
    if not step:
        return value
    name = step[0]
    args = step[1:]
    fn = TRANSFORMS.get(name)
    if fn is None:
        raise UnknownTransform(f"unknown transform: {name!r} (allowed: {sorted(TRANSFORMS)})")
    return fn(value, *args)


def apply_chain(value: Any, chain: Optional[list]) -> Any:
    """transform chain 을 순서대로 적용. value 가 None 이 되면 즉시 중단.

    chain 의 step 중 하나가 예외를 던지면 apply_chain 도 그대로 던진다(호출 측이
    잡아서 다음 fallback 으로 넘어가게).
    """
    if not chain:
        return value
    cur = value
    for step in chain:
        if cur is None:
            return None
        cur = apply_one(cur, step)
    return cur


def transform_names() -> list[str]:
    return sorted(TRANSFORMS)
