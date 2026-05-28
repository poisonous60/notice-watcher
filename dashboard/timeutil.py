"""dashboard 시간 표시 통일.

서버는 어떤 입력(ISO 문자열·epoch·datetime·이미 포맷된 "YYYY-MM-DD HH:MM:SS")이든
`<time class="nw-ts" datetime="ISO" data-kind="...">label</time>` 마크업으로 emit.
brower JS (base.html) 가 localStorage `nw.timeFormat` 에 따라 textContent 재포맷.

- TZ 없으면 UTC 가정 (DB convention — datetime.now(timezone.utc).isoformat).
- 빈/None/'—' → Markup '—' (재포맷 대상 아님).
- 라벨 default = `full` (YYYY-MM-DD HH:MM:SS, KST).
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from markupsafe import Markup, escape

_KST = timezone(timedelta(hours=9))


def parse_any(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s or s in ("—", "-", "None"):
        return None
    s2 = s[:-1] + "+00:00" if s.endswith("Z") else s
    try:
        d = datetime.fromisoformat(s2)
    except ValueError:
        # "YYYY-MM-DD HH:MM:SS" 슬라이스, 또는 "YYYY-MM-DD" 만
        for cut in (19, 16, 10):
            try:
                d = datetime.fromisoformat(s2[:cut])
                break
            except ValueError:
                continue
        else:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def _label(dt: datetime, kind: str) -> str:
    k = dt.astimezone(_KST)
    if kind == "short":
        return k.strftime("%m-%d %H:%M")
    if kind == "date":
        return k.strftime("%Y-%m-%d")
    if kind == "time":
        return k.strftime("%H:%M:%S")
    return k.strftime("%Y-%m-%d %H:%M:%S")


def render_ts(value: Any, kind: str = "full") -> Markup:
    """Jinja filter: `{{ value|ts }}` / `{{ value|ts('short') }}`.

    kinds: full | short | date | time. JS 가 사용자 pref 로 덮어쓰지만,
    `nw.timeFormat=full` 일 땐 이 서버 kind 가 그대로 노출됨.
    """
    dt = parse_any(value)
    if dt is None:
        return Markup("—")
    iso = dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    label = _label(dt, kind)
    return Markup(
        f'<time class="nw-ts" datetime="{escape(iso)}" data-kind="{escape(kind)}">'
        f'{escape(label)}</time>'
    )
