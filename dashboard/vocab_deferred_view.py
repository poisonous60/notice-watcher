"""`/vocab-deferred` 라우트 — closed vocab 확장 deferred 후보 표 + alert history.

dev box 전용. ADR `docs/adr/0003-vocabulary-extension-skill.md`.

- case .md frontmatter 의 `vocab_candidates` 모음 → 후보별 (confidence 분포 + cases) 표시.
- `output/vocab_alerts.json` 의 후보별 keyed history (first_seen / last_seen / alert_count / last_trigger_count).
- 임계 룰: high>=1 + total>=3 또는 med>=3 = triggered. low only = sub_threshold. high+low 공존 = contradiction.
- 사용자가 `/vocabulary-extension` SKILL 호출 검토할 시점 파악용.

routes:
  GET /vocab-deferred — 표
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse

from dashboard import state


def _query_vocab_trigger() -> dict:
    """`cases_index.py vocab-trigger --json --no-write` 를 호출해 결과 dict 반환.

    --no-write 이유: dashboard view 렌더가 history 쓰기를 트리거하면 안 됨 (사용자 의도 X).
    history 적재는 hand-config §5 step 10 의 `--silent-if-empty` 호출만이 권한.
    """
    root = Path(__file__).resolve().parent.parent
    cmd = [
        sys.executable,
        str(root / "scripts" / "cases_index.py"),
        "vocab-trigger",
        "--json",
        "--no-write",
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=str(root))
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"error": f"subprocess failed: {e}"}
    if res.returncode != 0:
        return {"error": f"exit {res.returncode}: {res.stderr.strip()[:300]}"}
    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError as e:
        return {"error": f"json decode: {e}", "raw": res.stdout[:300]}


def _read_alert_history() -> dict:
    """`output/vocab_alerts.json` 직접 읽기 — keyed history (candidate → first_seen / last_seen / alert_count / last_trigger_count)."""
    root = Path(__file__).resolve().parent.parent
    alert_file = root / "output" / "vocab_alerts.json"
    if not alert_file.exists():
        return {"first_alert_at": None, "candidates": {}}
    try:
        data = json.loads(alert_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"first_alert_at": None, "candidates": {}}
        data.setdefault("candidates", {})
        data.setdefault("first_alert_at", None)
        return data
    except (json.JSONDecodeError, OSError):
        return {"first_alert_at": None, "candidates": {}}


def register(app, templates, _render):
    @app.get("/vocab-deferred", response_class=HTMLResponse)
    async def vocab_deferred_page(request: Request):
        trigger = _query_vocab_trigger()
        history = _read_alert_history()

        # candidate name → history slot merge
        triggered = trigger.get("triggered") or []
        sub_threshold = trigger.get("sub_threshold") or []
        contradictions = trigger.get("contradictions") or []
        hist_candidates = history.get("candidates") or {}

        def _merge(entry: dict) -> dict:
            slot = hist_candidates.get(entry["candidate"]) or {}
            entry["history"] = slot
            return entry

        triggered = [_merge(dict(e)) for e in triggered]
        sub_threshold = [_merge(dict(e)) for e in sub_threshold]

        # contradictions 는 keyed 가 다른 구조 — 별도 처리
        contradictions = [dict(c) for c in contradictions]

        total_alerts = sum(int(s.get("alert_count", 0))
                           for s in hist_candidates.values())

        return _render(
            "vocab_deferred.html",
            request,
            triggered=triggered,
            sub_threshold=sub_threshold,
            contradictions=contradictions,
            history=history,
            total_alerts=total_alerts,
            candidates_total=trigger.get("candidates_total", 0),
            threshold=trigger.get("threshold", 3),
            error=trigger.get("error"),
            active="vocab",
        )
