"""`/history` 페이지 — `output/control_audit.jsonl` 에 한 줄씩 append 된 dashboard 액션 로그를
tail·파싱·필터해서 표로 표시.

control_actions.audit() 호출자만이 이 파일에 씀. 매 액션 row 1줄 — append-only, 회전 X.
파일이 너무 자라면 사용자가 직접 rotate 또는 truncate.

설계:
- 매 페이지 진입 시 마지막 N 줄만 read (`MAX_TAIL_LINES`). 큰 파일도 read 부담 X.
- 행 클릭(또는 `trace_id` 컬럼) → `/timings/{trace_id}` 점프. shell.async_run 이 결과 dict 에
  trace_id 추가, run_remote/run_push 가 audit detail 에 끼움 → 여기서 표시.
- 필터: category (remote/push/save/users …), ok/fail, slug/args 검색 (free-text).
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
    """파일 끝에서 N 줄만 read. 큰 파일도 RAM 절약 — chunk 거꾸로 읽기."""
    if not path.exists():
        return []
    try:
        size = path.stat().st_size
    except OSError:
        return []
    if size == 0:
        return []
    # 단순 구현: 작은 audit log 라 통째 read 후 split 으로 충분. 100MB+ 되면 chunk reverse 로 바꿈.
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
    """ISO-8601 UTC → 'YYYY-MM-DD HH:MM:SS KST'. 파싱 실패 시 raw."""
    if not iso:
        return ""
    try:
        # `+00:00` suffix Python 3.11+ fromisoformat 인식. 옛 포맷도 한 번 시도.
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_KST).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return iso


def _split_action(action: str) -> tuple[str, str]:
    """`remote.poll-now-slug` → ('remote', 'poll-now-slug'). 점 없으면 ('', action)."""
    if "." in action:
        cat, _, name = action.partition(".")
        return cat, name
    return "", action


def _slug_of(detail) -> Optional[str]:
    """detail 에서 가능한 slug 추출 — args[0] 이 slug 인 verb 가 많음."""
    if not isinstance(detail, dict):
        return None
    if "slug" in detail and isinstance(detail["slug"], str):
        return detail["slug"]
    if "slugs" in detail and isinstance(detail["slugs"], str):
        return detail["slugs"]
    args = detail.get("args")
    if isinstance(args, list) and args and isinstance(args[0], str):
        # poll-now-slug, replay-deliveries, notify-target 등 args[0] = slug
        return args[0]
    return None


CATEGORIES = ("remote", "push", "save", "users")


def load_rows(*, limit: int = 200, category: str = "",
              only_failed: bool = False, q: str = "") -> tuple[list[dict], int]:
    """audit jsonl tail → 필터 → 표시용 dict list. 두 번째 반환값 = 총 raw 줄 수.

    최신 행이 위. limit 적용 후 잘림.
    """
    raw_lines = _tail_lines(AUDIT_PATH, MAX_TAIL_LINES)
    total = len(raw_lines)
    rows: list[dict] = []
    q_lower = (q or "").strip().lower()
    cat_filter = (category or "").strip().lower()

    for line in reversed(raw_lines):
        d = _parse_line(line)
        if not d:
            continue
        action = str(d.get("action") or "")
        cat, name = _split_action(action)
        if cat_filter and cat != cat_filter:
            continue
        ok = bool(d.get("ok"))
        if only_failed and ok:
            continue
        detail = d.get("detail")
        slug = _slug_of(detail)
        # detail 안의 trace_id (run_remote/run_push 가 끼워준 경우만 존재)
        trace_id = None
        if isinstance(detail, dict):
            tid = detail.get("trace_id")
            if isinstance(tid, str) and tid:
                trace_id = tid
        rc = None
        if isinstance(detail, dict):
            rcv = detail.get("rc")
            if isinstance(rcv, int):
                rc = rcv

        if q_lower:
            # 자유 텍스트 검색 — slug/action/detail JSON 에 부분 매치
            hay = (slug or "") + " " + action + " " + json.dumps(detail, ensure_ascii=False) \
                if detail is not None else (slug or "") + " " + action
            if q_lower not in hay.lower():
                continue

        rows.append({
            "ts_iso": d.get("ts") or "",
            "ts_kst": _ts_to_kst_str(d.get("ts") or ""),
            "category": cat,
            "name": name,
            "action": action,
            "ok": ok,
            "rc": rc,
            "slug": slug,
            "trace_id": trace_id,
            "detail_json": json.dumps(detail, ensure_ascii=False, indent=2)
                if detail is not None else "",
        })
        if len(rows) >= limit:
            break

    return rows, total


__all__ = ["load_rows", "CATEGORIES", "MAX_TAIL_LINES", "AUDIT_PATH"]
