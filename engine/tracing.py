"""경량 분산 트레이싱 — Jaeger-스타일 span tree 를 JSONL 로 출력.

목표: dashboard `/timings` 페이지가 poll/notify/probe 워크플로우의 실측 시간을 gantt 로
표시. 외부 의존성 0 (OpenTelemetry 안 씀 — 우리 규모엔 과함).

활성화:
  env TRACE_ENABLED=1 일 때만 파일 IO 발생. 끄면 모든 span 호출이 no-op (zero-cost).

데이터 모델:
  - 한 trace = 한 워크플로우 run. trace_id = `YYYYMMDDHHMMSS_<6hex>` (21자, 시간순 정렬).
  - 한 span = (trace_id, span_id, parent_id, name, attrs, t_start_wall, t_end_wall,
              duration_ms, ok, err). 부모 추적은 contextvars 로 asyncio.gather 안전.
  - 파일: `output/traces/<trace_id>.jsonl` (각 줄 = span 1개. 마지막에 trace close 메타).
  - 인덱스: `output/traces/index.<kind>.jsonl` (kind=poll|notify|probe|…). 시작 시 1줄,
    종료 시 1줄 append. dashboard 가 join 해서 list 렌더 — 종료줄 없으면 '진행 중/crashed'.

cross-process linking:
  부모 trace 가 subprocess 를 띄울 때 env 로 `TRACE_ID`, `TRACE_PARENT_SPAN`,
  `TRACE_KIND` 전달. 자식 process 의 `start_trace()` 가 그 env 를 보면 새 trace_id 안
  만들고 그대로 이어씀 + 첫 span 의 parent = TRACE_PARENT_SPAN. → 멀티프로세스가 한 trace
  안에서 연속된 span 으로 보임.

  dev박스 dashboard 가 SSH 로 N100 호출 시도 같은 메커니즘: dev박스가 trace_id 생성 →
  env 로 N100 subprocess 에 전달 → N100 이 그 trace_id 로 inner spans 작성 → dev박스
  outer span 1개가 SSH overhead 까지 포함해 wrap.

JSONL 동시쓰기:
  process 안 spans 는 메모리 버퍼 (`_spans` list). `Trace.close()` 에서 한번에 write
  → asyncio.gather 의 동시 코루틴이 같은 파일에 동시 write 하는 race 차단.

crash 처리:
  trace 시작 시 index 에 `event=start` 줄 append. `close()` 가 `event=end` 줄 append.
  비정상 종료면 end 줄 없음 → dashboard 에서 '진행 중/crashed' 로 표시. (`with` 블록을 정상
  빠져나가면 항상 close 됨 — 강제종료/OOM 시엔 end 줄 누락이 곧 crash 신호.)

retention:
  `start_trace` 호출 시 cap (기본 500개, 60일 초과) 넘으면 오래된 trace 파일 prune.
  cheap O(N) — 파일 수가 수천이 안 됨.

span attrs 예시:
  poll.site: {slug, strategy, adapter, n_posts, n_new, broken}
  fetch_list: {slug, n_posts}
  body_fetch: {slug, post_id, http_status?, bytes?}
  summarize_gemini: {slug, post_id, model, tokens_in?, cost_usd?}
  filter_gemini: {slug, post_id, target_kind, target_id, model, passed}
  discord_deliver: {slug, post_id, target_kind, target_id, ok}

API:
  from engine.tracing import start_trace
  with start_trace("poll", attrs={"slugs": csv}) as tr:   # tr 이 None 일 수 있음 (disabled)
      with tr.span("fetch_list", attrs={"slug": s}):
          ...

  비활성일 때도 `with start_trace(...) as tr` 가 dummy 객체 반환 — 호출자는 None 체크 불필요.
"""
from __future__ import annotations

import contextvars
import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# --------------------------------------------------------------------------- #
# 경로·환경변수·상수
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parent.parent
TRACES_DIR = ROOT / "output" / "traces"

ENV_FLAG = "TRACE_ENABLED"
ENV_TRACE_ID = "TRACE_ID"
ENV_PARENT_SPAN = "TRACE_PARENT_SPAN"
ENV_KIND = "TRACE_KIND"

RETENTION_MAX_FILES = 500
RETENTION_MAX_AGE_SEC = 60 * 24 * 3600  # 60 일
TRACE_ID_FMT_LEN = 21  # YYYYMMDDHHMMSS_xxxxxx

_TRACE_ID_VALID_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
)


def is_enabled() -> bool:
    return os.environ.get(ENV_FLAG, "").strip().lower() in ("1", "true", "yes", "on")


def valid_trace_id(s: str) -> bool:
    """dashboard 라우트·remote.py allowlist 가 양쪽에서 호출. path-traversal 가드."""
    if not s or len(s) > 64:
        return False
    return all(c in _TRACE_ID_VALID_CHARS for c in s)


def new_trace_id() -> str:
    """`YYYYMMDDHHMMSS_<6hex>` — 시간순 정렬 가능, 충돌 ~0."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{ts}_{secrets.token_hex(3)}"  # 3 bytes = 6 hex chars


def new_span_id() -> str:
    return secrets.token_hex(4)  # 8 hex chars


# --------------------------------------------------------------------------- #
# contextvars — asyncio.gather 안전. thread-local 은 동시 코루틴이 같은 슬랏 공유라 깨짐.
# --------------------------------------------------------------------------- #
_current_trace: contextvars.ContextVar[Optional["Trace"]] = contextvars.ContextVar(
    "_trace_current_trace", default=None
)
_current_span_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "_trace_current_span_id", default=None
)


# --------------------------------------------------------------------------- #
# Span / Trace
# --------------------------------------------------------------------------- #
class _NoopSpan:
    """비활성·내부 자식 span 의 stand-in. 모든 메서드 no-op."""

    def __enter__(self) -> "_NoopSpan":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def set_attr(self, key: str, value: Any) -> None:
        return None


class _NoopTrace:
    """비활성 모드 — `with start_trace(...) as tr: with tr.span(...): ...` 가 그대로 돌게.

    `__enter__` 가 contextvar 도 자기 자신으로 셋업 → `current_trace()` 호출하는 inner
    함수들이 None 받지 않고 NoopTrace 받아 `tr.span(...)` 가 no-op 으로 동작.
    """

    trace_id: Optional[str] = None
    enabled: bool = False

    def __init__(self) -> None:
        self._token = None

    def span(self, name: str, attrs: Optional[dict] = None) -> _NoopSpan:
        return _NoopSpan()

    def env_for_child(self) -> dict:
        """비활성이면 자식 process 도 비활성 — env 안 넘김 (즉 부모 env 그대로)."""
        return {}

    def close(self, ok: bool = True, err: Optional[str] = None) -> None:
        return None

    def __enter__(self) -> "_NoopTrace":
        self._token = _current_trace.set(self)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._token is not None:
            try:
                _current_trace.reset(self._token)
            except (LookupError, ValueError):
                pass
            self._token = None
        return None


def _new_noop() -> _NoopTrace:
    """매 호출마다 새 _NoopTrace — 같은 인스턴스 공유하면 동시 호출 시 _token 덮어쓰기 race."""
    return _NoopTrace()


class _Span:
    __slots__ = ("trace", "span_id", "parent_id", "name", "attrs",
                 "t_start_wall", "t_end_wall", "_mono_start", "duration_ms",
                 "ok", "err", "_token", "_finished")

    def __init__(self, trace: "Trace", name: str, attrs: Optional[dict],
                 parent_id: Optional[str]):
        self.trace = trace
        self.span_id = new_span_id()
        self.parent_id = parent_id
        self.name = name
        self.attrs: dict = dict(attrs) if attrs else {}
        self.t_start_wall = time.time()
        self._mono_start = time.monotonic_ns()
        self.t_end_wall: Optional[float] = None
        self.duration_ms: Optional[float] = None
        self.ok: bool = True
        self.err: Optional[str] = None
        self._token = None
        self._finished = False

    def __enter__(self) -> "_Span":
        self._token = _current_span_id.set(self.span_id)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self._finished:
            self.t_end_wall = time.time()
            self.duration_ms = (time.monotonic_ns() - self._mono_start) / 1_000_000.0
            if exc_type is not None:
                self.ok = False
                self.err = f"{exc_type.__name__}: {exc}"
            self._finished = True
            self.trace._record(self)
        if self._token is not None:
            _current_span_id.reset(self._token)
            self._token = None
        # 예외 그대로 전파.

    def set_attr(self, key: str, value: Any) -> None:
        self.attrs[key] = value


class Trace:
    """active trace. process 안 lifetime — start_trace() 가 만들고 close() 가 닫음.

    `with start_trace(...) as tr` 가 contextmanager — 자동 close.
    """

    def __init__(self, trace_id: str, kind: str, attrs: Optional[dict],
                 parent_span: Optional[str], is_root: bool):
        self.trace_id = trace_id
        self.kind = kind
        self.attrs = dict(attrs) if attrs else {}
        self.parent_span = parent_span
        self.is_root = is_root  # True 면 index 에 start/end 줄 씀. child trace 는 안 씀.
        self.t_start_wall = time.time()
        self.t_end_wall: Optional[float] = None
        self._spans: list[_Span] = []
        self._closed = False
        self._token_trace = None
        self._token_span = None
        self.enabled = True

    # context manager — `with start_trace(...) as tr:` 형태.
    def __enter__(self) -> "Trace":
        self._token_trace = _current_trace.set(self)
        # root span 의 부모 = env 에서 받은 parent_span (있으면) 또는 None.
        # 자식 trace 가 부모 trace 안에 nested 라면 parent_span 은 부모의 active span id.
        if self.parent_span:
            self._token_span = _current_span_id.set(self.parent_span)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        ok = exc_type is None
        err = f"{exc_type.__name__}: {exc}" if exc_type else None
        self.close(ok=ok, err=err)
        if self._token_span is not None:
            _current_span_id.reset(self._token_span)
            self._token_span = None
        if self._token_trace is not None:
            _current_trace.reset(self._token_trace)
            self._token_trace = None

    def span(self, name: str, attrs: Optional[dict] = None) -> _Span:
        parent = _current_span_id.get()
        return _Span(self, name, attrs, parent_id=parent)

    def _record(self, sp: _Span) -> None:
        self._spans.append(sp)

    def env_for_child(self) -> dict:
        """subprocess 띄울 때 env 로 합쳐 자식 trace 가 같은 trace_id 안에서 이어쓰게 함."""
        return {
            ENV_FLAG: "1",
            ENV_TRACE_ID: self.trace_id,
            ENV_KIND: self.kind,
            ENV_PARENT_SPAN: _current_span_id.get() or "",
        }

    def close(self, ok: bool = True, err: Optional[str] = None) -> None:
        if self._closed:
            return
        self._closed = True
        self.t_end_wall = time.time()
        # 1) span 파일 write
        try:
            TRACES_DIR.mkdir(parents=True, exist_ok=True)
            jsonl_path = TRACES_DIR / f"{self.trace_id}.jsonl"
            file_existed = jsonl_path.exists() and jsonl_path.stat().st_size > 0
            with jsonl_path.open("a", encoding="utf-8") as f:
                # 파일이 비었으면 trace 메타 1줄. cross-process 자식이 부모보다 먼저 close
                # 할 수도 있으니 is_root 만으로 판단하지 X — 파일 비어있음으로 1회만 보장.
                if not file_existed:
                    meta = {
                        "type": "trace",
                        "trace_id": self.trace_id,
                        "kind": self.kind,
                        "attrs": self.attrs,
                        "t_start_wall": self.t_start_wall,
                        "t_end_wall": self.t_end_wall,
                        "ok": ok,
                        "err": err,
                        "pid": os.getpid(),
                    }
                    f.write(json.dumps(meta, ensure_ascii=False) + "\n")
                for sp in self._spans:
                    rec = {
                        "type": "span",
                        "trace_id": self.trace_id,
                        "span_id": sp.span_id,
                        "parent_id": sp.parent_id,
                        "name": sp.name,
                        "attrs": sp.attrs,
                        "t_start_wall": sp.t_start_wall,
                        "t_end_wall": sp.t_end_wall,
                        "duration_ms": sp.duration_ms,
                        "ok": sp.ok,
                        "err": sp.err,
                    }
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass  # trace 작성 실패가 본 작업 막으면 안 됨.

        # 2) index 에 end 줄 append (root trace 만).
        if self.is_root:
            try:
                idx_path = TRACES_DIR / f"index.{self.kind}.jsonl"
                line = {
                    "event": "end",
                    "trace_id": self.trace_id,
                    "kind": self.kind,
                    "attrs": self.attrs,
                    "t_start_wall": self.t_start_wall,
                    "t_end_wall": self.t_end_wall,
                    "duration_ms": (self.t_end_wall - self.t_start_wall) * 1000.0,
                    "n_spans": len(self._spans),
                    "ok": ok,
                    "err": err,
                }
                with idx_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(line, ensure_ascii=False) + "\n")
            except OSError:
                pass

def start_trace(kind: str, attrs: Optional[dict] = None) -> Any:
    """현재 process 의 root trace 시작 — `with start_trace(...) as tr:` 로 사용.

    env 로 부모 trace_id 가 들어와 있으면 그걸 그대로 이어씀 (cross-process linking).
    그 경우 is_root=False — index 에 start/end 줄 안 씀 (부모가 씀).
    """
    if not is_enabled():
        return _new_noop()

    parent_trace_id = (os.environ.get(ENV_TRACE_ID) or "").strip()
    parent_span = (os.environ.get(ENV_PARENT_SPAN) or "").strip() or None

    if parent_trace_id and valid_trace_id(parent_trace_id):
        # subprocess 안 — 부모가 만든 trace 그대로 이어씀.
        trace = Trace(parent_trace_id, kind=kind, attrs=attrs,
                      parent_span=parent_span, is_root=False)
    else:
        # 최상위 — 새 trace_id 생성 + index 에 start 줄.
        tid = new_trace_id()
        trace = Trace(tid, kind=kind, attrs=attrs, parent_span=None, is_root=True)
        # index start 줄.
        try:
            TRACES_DIR.mkdir(parents=True, exist_ok=True)
            idx_path = TRACES_DIR / f"index.{kind}.jsonl"
            line = {
                "event": "start",
                "trace_id": tid,
                "kind": kind,
                "attrs": dict(attrs) if attrs else {},
                "t_start_wall": trace.t_start_wall,
                "pid": os.getpid(),
            }
            with idx_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        except OSError:
            pass
        # retention prune — 새 root trace 마다 한번. 거의 cheap.
        _prune_old_traces()

    return trace


_PROCESS_NOOP = _NoopTrace()


def current_trace():
    """contextvar 에 active trace 가 있으면 그것, 없으면 noop 인스턴스. 절대 None 아님 —
    inner 함수가 `tr = current_trace(); with tr.span(...)` 패턴을 None-가드 없이 쓸 수 있게.
    """
    tr = _current_trace.get()
    return tr if tr is not None else _PROCESS_NOOP


def current_span_id() -> Optional[str]:
    return _current_span_id.get()


# --------------------------------------------------------------------------- #
# subprocess env helper — 호출자가 `subprocess.run(..., env={**os.environ, **env_for_child()})`
# --------------------------------------------------------------------------- #
def env_for_child() -> dict:
    """현재 trace 의 env (subprocess 에 부모-자식 link)."""
    tr = current_trace()
    if tr is None or not getattr(tr, "enabled", False):
        return {}
    return tr.env_for_child()


# --------------------------------------------------------------------------- #
# retention prune
# --------------------------------------------------------------------------- #
def _prune_old_traces() -> None:
    """파일 수 / 나이 cap 으로 prune. index 줄은 건드리지 X — dashboard 가 missing 파일 처리."""
    try:
        if not TRACES_DIR.exists():
            return
        files = [p for p in TRACES_DIR.glob("*.jsonl") if not p.name.startswith("index.")]
        now = time.time()
        # 나이 cap.
        too_old = [p for p in files if (now - p.stat().st_mtime) > RETENTION_MAX_AGE_SEC]
        for p in too_old:
            try:
                p.unlink()
            except OSError:
                pass
        # 파일 수 cap.
        survivors = sorted(
            (p for p in TRACES_DIR.glob("*.jsonl") if not p.name.startswith("index.")),
            key=lambda p: p.stat().st_mtime,
        )
        if len(survivors) > RETENTION_MAX_FILES:
            for p in survivors[: len(survivors) - RETENTION_MAX_FILES]:
                try:
                    p.unlink()
                except OSError:
                    pass
    except OSError:
        pass
