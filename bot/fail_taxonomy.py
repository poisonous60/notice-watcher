"""jobs.status='failed' 안의 fail_kind/fail_subkind 분류 — `result_rc` + `result_tail` 에서 파생.

`/jobs` 대시보드가 "failed" 한 버킷에 뭉친 4 가지(LLM gen 실패 / policy 거부 / gate 거부 /
시스템 결함)를 구분 표시하려 read time 에 호출. DB 컬럼 추가 X (ADR 0002).

분류 룰:
- 1차 (rc 단독, deterministic): done(0) / gen_fail(1) / policy_reject(2) / gate_reject(3) /
  bug(-1/-2/-3/-99). pending/running 은 그대로 통과.
- 2차 (`result_tail` regex): `register.py` 의 안정적 print 라인을 잡음.
  - gen_fail → 마지막 `[FAIL] <check>` 매치 (`posts_nonempty` / `article_body_len` /
    `published_at_iso` / `post_id_*` / `title_nonempty`) 또는 `gemini_api`.
  - policy_reject → `LOGIN_REQUIRED` / `BLOCKED_BOT` / `BLOCKED_IP` / `BLOCKED_GEO` 토큰.
  - gate_reject → 게이트별 print 라인 (`recognize_reject (...)` / `nav-only same-host` /
    `meta 선언 + 발산` / `multi-host hub root` / `게시판 형식 아님`).
  - bug → rc 직접 매핑 (chromium_lock_timeout / subprocess_timeout / subprocess_exception /
    worker_exception).

tail 은 `bot/site_ops.py:226` 가 last ~4000 chars 만 보존 — 잘려도 마지막 print 라인은 살아남는다.
"""
from __future__ import annotations

import re
from typing import Optional


_FAIL_CHECK_RE = re.compile(r"\[FAIL\]\s+([A-Za-z_][A-Za-z0-9_]*)")
_RECOGNIZER_RE = re.compile(r"recognize_reject\s+\(([^)]+)\)")

_BUG_RC_TO_SUB = {
    -1: "chromium_lock_timeout",
    -2: "subprocess_timeout",
    -3: "subprocess_exception",
    -5: "attempts_limit",
    -99: "worker_exception",
}


def classify_fail(status: Optional[str], rc: Optional[int], tail: Optional[str]
                  ) -> tuple[str, Optional[str], Optional[str]]:
    """jobs row 의 (fail_kind, fail_subkind, reason_short) 계산.

    Returns:
        fail_kind: pending / running / done / gen_fail / policy_reject / gate_reject / bug /
            unknown 중 하나.
        fail_subkind: 1차 안의 sub 식별자 (None 가능 — 매칭 안 됐을 때).
        reason_short: tail 의 마지막 의미있는 줄 (≤200 chars). 셀 hover/title 용. None 가능.
    """
    s = (status or "").lower()
    if s in ("pending", "running"):
        return (s, None, None)
    if s == "done":
        return ("done", None, None)
    # status='failed' AND rc=0 = worker race (`bot/worker.py:286` `ok = (rc == 0) and is_registered(slug)` —
    # subprocess 성공 했는데 state.json 미작성). done 으로 가리지 X — bug 로 surface.
    if s != "failed" and rc == 0:
        return ("done", None, None)

    reason = _last_meaningful_line(tail)

    if rc in _BUG_RC_TO_SUB:
        return ("bug", _BUG_RC_TO_SUB[rc], reason)

    if s == "failed" and rc == 0:
        return ("bug", "registered_but_no_state", reason)

    t = tail or ""

    if rc == 1:
        matches = _FAIL_CHECK_RE.findall(t)
        if matches:
            sub = matches[-1]
        elif "gemini 호출" in t or "RESOURCE_EXHAUSTED" in t or "UNAVAILABLE" in t:
            sub = "gemini_api"
        else:
            sub = None
        return ("gen_fail", sub, reason)

    if rc == 2:
        if "LOGIN_REQUIRED" in t:
            sub = "login_required"
        elif "BLOCKED_BOT" in t:
            sub = "blocked_bot"
        elif "BLOCKED_IP" in t:
            sub = "blocked_ip"
        elif "BLOCKED_GEO" in t:
            sub = "blocked_geo"
        else:
            sub = None
        return ("policy_reject", sub, reason)

    if rc == 3:
        m = _RECOGNIZER_RE.search(t)
        if m:
            sub = f"recognizer:{m.group(1).strip()}"
        elif "nav-only same-host" in t:
            sub = "nav_only"
        elif "meta 선언 + 발산" in t:
            sub = "meta_diverging"
        elif "multi-host hub root" in t:
            sub = "multi_host_hub"
        elif "게시판 형식 아님" in t:
            sub = "board_shape"
        else:
            sub = None
        return ("gate_reject", sub, reason)

    return ("unknown", None, reason)


def _last_meaningful_line(tail: Optional[str]) -> Optional[str]:
    if not tail:
        return None
    for line in reversed(tail.splitlines()):
        s = line.strip()
        if s:
            return s[:200]
    return None


# `bot/db.py` 의 jobs.status CHECK 값 — `/jobs` filter 가 fail_kind 인지 status 인지 분기 + SQL pushdown 에 씀.
BASE_STATUS_VALUES: frozenset[str] = frozenset({"pending", "running", "done", "failed"})
