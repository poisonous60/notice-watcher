"""`/timings` 페이지 — N100 의 `output/traces/index.<kind>.jsonl` 을 SSH 로 가져와
파싱·정렬·필터. 단일 trace 상세는 lazy fetch + 로컬 캐시.

설계:
  - index 는 매 요청 SSH cat (작음, ≤수MB). per-trace JSONL 은 클릭 시점에만 fetch,
    `output/snapshot/traces/<trace_id>.jsonl` 에 캐시.
  - render 자체는 서버사이드 — SVG gantt 도 Jinja 매크로가 그림. JS 0줄.

trace_id 검증:
  - dashboard 라우트 + remote.py 양쪽 validate. 여기선 engine.tracing.valid_trace_id 재사용.

미완료 trace:
  - index 에 `event=start` 줄만 있고 `event=end` 줄 없는 것 = 진행 중 또는 crashed.
  - dashboard 가 그런 항목을 `status=running` 으로 표시. (실측 close 시각 없음).
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from engine.tracing import valid_trace_id

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "output" / "snapshot" / "traces"
LOCAL_TRACES_DIR = ROOT / "output" / "traces"
REMOTE_SCRIPT = ROOT / "scripts" / "remote.py"
TRACE_SOURCES = ("snapshot", "local")

# index 줄에 들어오는 kind 들 — UI 필터 옵션 source.
KNOWN_KINDS = ("poll", "poll_and_notify", "notify", "notify_idle", "probe", "probe_reprobe")


@dataclass
class IndexEntry:
    trace_id: str
    kind: str
    attrs: dict
    t_start_wall: float
    t_end_wall: Optional[float] = None
    duration_ms: Optional[float] = None
    n_spans: Optional[int] = None
    ok: Optional[bool] = None
    err: Optional[str] = None
    pid: Optional[int] = None
    started: bool = False
    ended: bool = False


@dataclass
class Span:
    trace_id: str
    span_id: str
    parent_id: Optional[str]
    name: str
    attrs: dict
    t_start_wall: float
    t_end_wall: Optional[float]
    duration_ms: Optional[float]
    ok: bool
    err: Optional[str]


@dataclass
class TraceDetail:
    trace_id: str
    kind: str
    attrs: dict
    t_start_wall: float
    t_end_wall: Optional[float]
    spans: list[Span] = field(default_factory=list)
    ok: Optional[bool] = None
    err: Optional[str] = None


def _run_blocking(cmd: list[str]) -> tuple[int, str, str]:
    p = subprocess.run(cmd, cwd=str(ROOT), stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True, errors="replace")
    return p.returncode, p.stdout or "", p.stderr or ""


async def _async_run(cmd: list[str]) -> tuple[int, str, str]:
    """Windows asyncio (SelectorEventLoop) 는 `create_subprocess_exec` 미지원 →
    `to_thread` 로 우회 (dashboard.shell.async_run 과 동일 패턴)."""
    return await asyncio.to_thread(_run_blocking, cmd)


async def fetch_index_all(source: str = "snapshot") -> tuple[bool, list[IndexEntry], str]:
    """모든 kind 의 index 합본을 가져옴 → IndexEntry list (start+end merge).

    source='snapshot' (기본): N100 의 `output/traces/index.*.jsonl` 을 SSH cat.
    source='local'         : dev box `output/traces/index.*.jsonl` 직접 read.
                             register_batch.py 같은 dev box 실행 트레이스 보기 용도.
    """
    if source == "local":
        return _fetch_index_local()
    rc, out, err = await _async_run([sys.executable, str(REMOTE_SCRIPT), "trace-index-all"])
    if rc != 0:
        return False, [], err or out
    return True, _parse_index_lines(out), ""


def _fetch_index_local() -> tuple[bool, list[IndexEntry], str]:
    """LOCAL_TRACES_DIR/index.*.jsonl 합본 → IndexEntry list. SSH 없이 직접 read."""
    if not LOCAL_TRACES_DIR.exists():
        return True, [], ""
    text_parts: list[str] = []
    for f in sorted(LOCAL_TRACES_DIR.glob("index.*.jsonl")):
        try:
            text_parts.append(f.read_text(encoding="utf-8", errors="replace"))
        except OSError as e:
            return False, [], f"local trace index read 실패 ({f.name}): {e}"
    return True, _parse_index_lines("\n".join(text_parts)), ""


def _parse_index_lines(text: str) -> list[IndexEntry]:
    by_id: dict[str, IndexEntry] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        tid = d.get("trace_id")
        if not isinstance(tid, str) or not valid_trace_id(tid):
            continue
        ev = d.get("event")
        e = by_id.get(tid)
        if e is None:
            e = IndexEntry(
                trace_id=tid, kind=str(d.get("kind") or "?"),
                attrs=d.get("attrs") or {},
                t_start_wall=float(d.get("t_start_wall") or 0.0),
                pid=d.get("pid"),
            )
            by_id[tid] = e
        if ev == "start":
            e.started = True
            e.t_start_wall = float(d.get("t_start_wall") or e.t_start_wall)
            if d.get("kind"):
                e.kind = str(d["kind"])
        elif ev == "end":
            e.ended = True
            if d.get("t_end_wall") is not None:
                e.t_end_wall = float(d["t_end_wall"])
            if d.get("duration_ms") is not None:
                e.duration_ms = float(d["duration_ms"])
            e.n_spans = d.get("n_spans")
            e.ok = d.get("ok")
            e.err = d.get("err")
            if d.get("kind"):
                e.kind = str(d["kind"])
    return list(by_id.values())


def filter_sort_entries(entries: list[IndexEntry], *,
                        kinds: Optional[set[str]] = None,
                        only_failed: bool = False,
                        include_idle: bool = False,
                        slug_q: Optional[str] = None,
                        limit: int = 100,
                        offset: int = 0) -> tuple[list[IndexEntry], bool]:
    """필터·정렬 후 offset/limit slice. 반환: (page_entries, has_next)."""
    out = entries
    if not include_idle:
        out = [e for e in out if e.kind != "notify_idle"]
    if kinds:
        out = [e for e in out if e.kind in kinds]
    if only_failed:
        out = [e for e in out if e.ok is False]
    if slug_q:
        ql = slug_q.lower()
        def _match(e: IndexEntry) -> bool:
            v = e.attrs or {}
            for key, val in v.items():
                if isinstance(val, str) and ql in val.lower():
                    return True
            return False
        out = [e for e in out if _match(e)]
    out.sort(key=lambda e: e.t_start_wall, reverse=True)
    has_next = (offset + limit) < len(out)
    return out[offset:offset + limit], has_next


# --------------------------------------------------------------------------- #
# 단일 trace 상세 — cache miss 면 SSH fetch.
# --------------------------------------------------------------------------- #
async def load_trace_detail(trace_id: str, source: str = "snapshot") -> Optional[TraceDetail]:
    """캐시 우선. 단 종료된 trace (meta 의 t_end_wall != None) 만 캐시 — 진행 중인 trace 가
    poisoning 되지 않게 매번 재 fetch.

    source='local' 면 LOCAL_TRACES_DIR/<trace_id>.jsonl 을 직접 read (SSH 안 함).
    """
    if not valid_trace_id(trace_id):
        return None
    if source == "local":
        p = LOCAL_TRACES_DIR / f"{trace_id}.jsonl"
        if not p.exists() or p.stat().st_size == 0:
            return None
        try:
            return _parse_trace(p.read_text(encoding="utf-8"), trace_id)
        except OSError:
            return None
    cache = CACHE_DIR / f"{trace_id}.jsonl"
    use_cache = False
    if cache.exists() and cache.stat().st_size > 0:
        # 캐시본 자체가 종료 trace 인지 빠르게 확인 — 첫 줄(meta) 의 t_end_wall.
        try:
            first = cache.open("r", encoding="utf-8").readline()
            d = json.loads(first)
            if d.get("type") == "trace" and d.get("t_end_wall") is not None:
                use_cache = True
        except (OSError, json.JSONDecodeError):
            pass
    if not use_cache:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        rc, out, err = await _async_run(
            [sys.executable, str(REMOTE_SCRIPT), "trace-fetch", trace_id]
        )
        if rc != 0 or not out:
            # cache 가 있으면 fallback (오래된 본).
            if cache.exists() and cache.stat().st_size > 0:
                pass
            else:
                return None
        else:
            cache.write_text(out, encoding="utf-8")
    text = cache.read_text(encoding="utf-8")
    return _parse_trace(text, trace_id)


def _parse_trace(text: str, trace_id: str) -> Optional[TraceDetail]:
    meta: Optional[dict] = None
    spans: list[Span] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("trace_id") != trace_id:
            continue
        t = d.get("type")
        if t == "trace":
            meta = d
        elif t == "span":
            spans.append(Span(
                trace_id=trace_id,
                span_id=str(d.get("span_id") or ""),
                parent_id=d.get("parent_id"),
                name=str(d.get("name") or "?"),
                attrs=d.get("attrs") or {},
                t_start_wall=float(d.get("t_start_wall") or 0.0),
                t_end_wall=(float(d["t_end_wall"]) if d.get("t_end_wall") is not None else None),
                duration_ms=(float(d["duration_ms"]) if d.get("duration_ms") is not None else None),
                ok=bool(d.get("ok", True)),
                err=d.get("err"),
            ))
    if meta is None and not spans:
        return None
    return TraceDetail(
        trace_id=trace_id,
        kind=str((meta or {}).get("kind") or "?"),
        attrs=(meta or {}).get("attrs") or {},
        t_start_wall=float((meta or {}).get("t_start_wall") or (spans[0].t_start_wall if spans else 0.0)),
        t_end_wall=((meta or {}).get("t_end_wall") if meta else None),
        spans=spans,
        ok=(meta or {}).get("ok"),
        err=(meta or {}).get("err"),
    )


# --------------------------------------------------------------------------- #
# Gantt 좌표 계산 — 템플릿에서 직접 호출.
# --------------------------------------------------------------------------- #
@dataclass
class GanttBar:
    span_id: str
    parent_id: Optional[str]
    name: str
    x: float          # px (시간축)
    width: float      # px (>=2)
    y: int            # px (초기 row 좌상단 — JS collapse 시 재계산)
    depth: int        # 트리 깊이 (0 = root span). 왼쪽 name 컬럼에서 indent 용.
    color_class: str
    tooltip: str
    duration_ms: float
    duration_str: str  # "0.587 s" — UI 표시용 미리 포매팅
    attrs: dict
    ok: bool
    err: Optional[str] = None
    children_ids: list = field(default_factory=list)  # 직속 자식 span_id 들 — JS collapse 용


def build_gantt(detail: TraceDetail, *, total_width: int = 1100, row_height: int = 22,
                min_bar_px: float = 2.0) -> dict:
    """spans → bars + 시간축. row 배치 = parent→child 트리 DFS 순서.

    이전 버전은 'lane 우선' (시간 충돌 없는 빈 lane 재사용) 이라 병렬 spans 가 나란히
    보였지만 부모-자식 관계가 안 보임. 이제: 부모 바로 아래에 자식 spans 가 (자식들끼리
    시작시각 순) 깊이 우선으로 박힘. 같은 parent 의 sibling 들은 시각상 연속된 row 묶음.
    `depth` 필드를 줘서 템플릿 왼쪽 name 컬럼에서 indent.
    """
    if not detail.spans:
        return {"bars": [], "total_width": total_width, "total_height": row_height,
                "t_min": detail.t_start_wall, "duration_ms": 0.0, "ticks": []}
    t_min = min(s.t_start_wall for s in detail.spans)
    t_max = max((s.t_end_wall or s.t_start_wall) for s in detail.spans)
    if detail.t_end_wall is not None:
        t_max = max(t_max, detail.t_end_wall)
    if detail.t_start_wall:
        t_min = min(t_min, detail.t_start_wall)
    total_sec = max(t_max - t_min, 0.001)
    px_per_sec = total_width / total_sec

    # parent → list[Span] (자식들). orphan 은 가상 None 부모 아래에 모음 (cross-process
    # 경계에서 부모 span 이 같은 파일에 안 보일 때 — 현 설계에선 거의 없음).
    span_ids: set[str] = {s.span_id for s in detail.spans}
    children: dict[Optional[str], list[Span]] = {}
    for s in detail.spans:
        # parent_id 가 같은 trace 안 span 으로 존재 안 하면 root 로 처리.
        parent_key = s.parent_id if (s.parent_id in span_ids) else None
        children.setdefault(parent_key, []).append(s)
    # 자식 묶음 안 정렬: 시작 시각 우선.
    for v in children.values():
        v.sort(key=lambda s: (s.t_start_wall, s.duration_ms or 0))

    bars: list[GanttBar] = []
    # DFS — root 들 → 각 root 의 자식 트리 재귀.
    def _emit(s: Span, depth: int) -> None:
        s_end = s.t_end_wall if s.t_end_wall is not None else s.t_start_wall
        x = max((s.t_start_wall - t_min) * px_per_sec, 0.0)
        width = max((s_end - s.t_start_wall) * px_per_sec, min_bar_px)
        if x + width > total_width:
            width = max(total_width - x, min_bar_px)
        y = len(bars) * row_height
        color = _color_for(s.name, ok=s.ok)
        dur = s.duration_ms if s.duration_ms is not None else (s_end - s.t_start_wall) * 1000.0
        tooltip = f"{s.name}  ({dur / 1000:.3f}s)\n" + _tooltip_attrs(s.attrs)
        if s.err:
            tooltip = f"⚠ {s.err}\n" + tooltip
        dur_str = f"{dur / 1000:.3f} s" if dur >= 100 else f"{dur:.1f} ms"
        kids = children.get(s.span_id, [])
        bars.append(GanttBar(
            span_id=s.span_id, parent_id=s.parent_id, name=s.name,
            x=x, width=width, y=y, depth=depth, color_class=color,
            tooltip=tooltip, duration_ms=dur, duration_str=dur_str,
            attrs=s.attrs, ok=s.ok, err=s.err,
            children_ids=[c.span_id for c in kids],
        ))
        for child in kids:
            _emit(child, depth + 1)

    for root in children.get(None, []):
        _emit(root, 0)

    total_height = max(len(bars) * row_height, row_height)
    ticks = _ticks(total_sec, px_per_sec)
    return {
        "bars": bars,
        "total_width": total_width,
        "total_height": total_height,
        "t_min": t_min,
        "duration_ms": total_sec * 1000.0,
        "ticks": ticks,
    }


def _color_for(name: str, *, ok: bool) -> str:
    if not ok:
        return "span-err"
    pref = name.split(".", 1)[0]
    mapping = {
        "poll": "span-poll",
        "fetch_list": "span-poll",
        "body_fetch": "span-poll",
        "body_fetch_all": "span-poll",
        "notify": "span-notify",
        "summarize_llm": "span-llm",
        "filter_llm": "span-llm",
        # 옛 span name (provider-neutral rename 이전) — 아카이브된 trace 색상 유지.
        "summarize_gemini": "span-llm",
        "filter_gemini": "span-llm",
        "discord_deliver": "span-notify",
        "probe": "span-probe",
        "chromium_lock_acquire": "span-lock",
        "poll_subprocess": "span-subp",
        "notify_subprocess": "span-subp",
    }
    return mapping.get(pref, mapping.get(name, "span-default"))


def _tooltip_attrs(attrs: dict) -> str:
    if not attrs:
        return ""
    parts = []
    for k, v in attrs.items():
        s = str(v)
        if len(s) > 60:
            s = s[:57] + "…"
        parts.append(f"{k}={s}")
    return "  ".join(parts)


def _ticks(total_sec: float, px_per_sec: float) -> list[dict]:
    """시간축 눈금 — 0~total_sec 사이 ~10개 균등."""
    if total_sec <= 0:
        return []
    target = 10
    step = total_sec / target
    nice_steps = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5,
                   1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0]
    step = min(nice_steps, key=lambda v: abs(v - step))
    out = []
    t = 0.0
    while t <= total_sec + 1e-6:
        x = t * px_per_sec
        if t >= 1.0:
            label = f"{t:.1f}s"
        else:
            label = f"{int(t * 1000)}ms"
        out.append({"x": x, "label": label})
        t += step
    return out
