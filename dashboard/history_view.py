"""`/history` 페이지 — `output/control_audit.jsonl` 에 한 줄씩 append 된 dashboard 액션 로그를
tail·파싱·필터해서 표로 표시. 행 형식은 `/timings` 와 동일 column 으로 맞춤.

control_actions.audit() 호출자만이 이 파일에 씀. 매 액션 row 1줄 — append-only, 회전 X.
파일이 너무 자라면 사용자가 직접 rotate 또는 truncate.

설계:
- 매 페이지 진입 시 마지막 N 줄만 read (`MAX_TAIL_LINES`). 큰 파일도 read 부담 X.
- 행 dict 키는 `/timings` 와 동일: ok/kind/t_start_str/duration_ms/n_spans/attrs_short/trace_id.
  audit 는 *완료 시점* 한 줄만 append 라 duration_ms·n_spans 데이터 없음 → 항상 None
  (template 가 "—" 표시). column 만 맞춰서 두 페이지 layout 통일.
- trace_id 가 있으면 `/timings/{trace_id}` 점프 링크 (shell.async_run 이 결과 dict 에 넣고
  run_remote/run_push 가 audit detail 에 끼움).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
AUDIT_PATH = ROOT / "output" / "control_audit.jsonl"

# 큰 파일 회피 — 마지막 N 줄만. UI 가 필터 후에도 충분히 보이게 넉넉히.
MAX_TAIL_LINES = 5000

_KST = timezone(timedelta(hours=9))


def _tail_lines(path: Path, n: int) -> list[str]:
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    return lines[-n:] if len(lines) > n else lines


def _parse_line(s: str) -> Optional[dict]:
    s = s.strip()
    if not s:
        return None
    try:
        d = json.loads(s)
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict):
        return None
    return d


def _ts_to_kst_str(iso: str) -> str:
    """ISO-8601 UTC 정규화 (TZ 없으면 UTC). 템플릿이 `|ts` 로 KST 변환."""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
    except ValueError:
        return ""


def _split_action(action: str) -> tuple[str, str]:
    if "." in action:
        cat, _, name = action.partition(".")
        return cat, name
    return "", action


def _attrs_short(detail) -> str:
    """detail dict → 'k=v  k=v ...' 한 줄. `/timings` 의 _attrs_short 동일 포맷.

    `trace_id` 는 별 컬럼에도 표시되므로 attrs 에서 제외 (중복 회피).
    """
    if not isinstance(detail, dict):
        return ""
    parts: list[str] = []
    for k, v in detail.items():
        if k == "trace_id":
            continue
        s = str(v)
        if len(s) > 40:
            s = s[:37] + "…"
        parts.append(f"{k}={s}")
        if sum(len(p) for p in parts) > 140:
            break
    return "  ".join(parts)


CATEGORIES = ("remote", "push", "save", "users")


def load_rows(*, limit: int = 200, offset: int = 0, category: str = "",
              only_failed: bool = False,
              q: str = "") -> tuple[list[dict], int, bool]:
    """audit jsonl tail → 필터 → 표시용 dict list. 반환: (rows, total_raw_lines, has_next).

    최신 행이 위. 행 dict 는 `/timings` 와 같은 키를 씀 — template 가 거의 동일 markup.
    필터·정렬 후 offset/limit slice 로 pagination 지원.
    """
    raw_lines = _tail_lines(AUDIT_PATH, MAX_TAIL_LINES)
    total = len(raw_lines)
    matched: list[dict] = []
    q_lower = (q or "").strip().lower()
    cat_filter = (category or "").strip().lower()
    # offset + limit + 1 까지만 수집 — has_next 판정용 +1, 더는 풀스캔 X.
    stop_at = offset + limit + 1

    for line in reversed(raw_lines):
        d = _parse_line(line)
        if not d:
            continue
        action = str(d.get("action") or "")
        cat, _name = _split_action(action)
        if cat_filter and cat != cat_filter:
            continue
        ok = bool(d.get("ok"))
        if only_failed and ok:
            continue
        detail = d.get("detail")

        trace_id = None
        if isinstance(detail, dict):
            tid = detail.get("trace_id")
            if isinstance(tid, str) and tid:
                trace_id = tid

        if q_lower:
            hay = action + " " + (json.dumps(detail, ensure_ascii=False)
                                  if detail is not None else "")
            if q_lower not in hay.lower():
                continue

        matched.append({
            "ok": ok,
            "kind": action,                              # remote.poll-now-slug 등 full action
            "t_start_str": _ts_to_kst_str(d.get("ts") or ""),
            "duration_ms": None,                         # audit 에 측정 없음
            "n_spans": None,
            "attrs_short": _attrs_short(detail),
            "trace_id": trace_id,
        })
        if len(matched) >= stop_at:
            break

    has_next = len(matched) > offset + limit
    rows = matched[offset:offset + limit]
    return rows, total, has_next


__all__ = ["load_rows", "CATEGORIES", "MAX_TAIL_LINES", "AUDIT_PATH"]
