"""LLMClient + UsageRecorder + prices 단위 테스트.

provider 별 HTTP 호출은 mock 안 함 — 베이스 클래스의 시간 측정·기록·cost 계산만 본다.
스타일: 다른 테스트와 동일하게 `run()` 반환 + `__main__` 실행.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional


# repo root 추가 (script 단독 실행 시)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


from generate.llm_base import LLMClient, LLMResponse, LLMHttpError, LLMQuotaError  # noqa: E402
from generate.usage_recorder import UsageRecorder  # noqa: E402
from generate import prices as prices_mod  # noqa: E402


class _FakeClient(LLMClient):
    provider = "fake"

    def __init__(self, *, model="fake-1", recorder=None, cost_fn=None,
                 raise_exc: Optional[Exception] = None,
                 fixed_text="ok", pt=10, ct=20, sleep_s=0.0,
                 raw_model: str = "fake-1-resolved") -> None:
        super().__init__(model=model, recorder=recorder, cost_fn=cost_fn)
        self._raise = raise_exc
        self._text = fixed_text
        self._pt = pt
        self._ct = ct
        self._sleep = sleep_s
        self._raw = raw_model

    def _do_request(self, *, system_instruction, user_text, temperature, json_mode):
        if self._sleep:
            time.sleep(self._sleep)
        if self._raise is not None:
            raise self._raise
        return LLMResponse(
            text=self._text,
            prompt_tokens=self._pt,
            completion_tokens=self._ct,
            total_tokens=self._pt + self._ct,
            raw_model=self._raw,
        )


def _tmp_db() -> Path:
    return Path(tempfile.mkdtemp()) / "u.sqlite3"


def run() -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []

    # ----- 1. 정상 호출: response 채워지고 recorder 1행 기록 -----
    db = _tmp_db()
    rec = UsageRecorder(db)
    cli = _FakeClient(recorder=rec, fixed_text="hello", pt=11, ct=22)
    resp = cli.generate(system_instruction="sys", user_text="ask",
                        call_site="config_generate", slug="s1", attempt=1)
    rows = sqlite3.connect(db).execute("SELECT * FROM llm_calls").fetchall()
    cases.append((
        "ok_response_fields",
        resp.text == "hello" and resp.prompt_tokens == 11 and resp.completion_tokens == 22
        and resp.total_tokens == 33 and resp.response_chars == len("hello")
        and resp.prompt_chars == len("sys") + len("ask"),
        f"got resp={resp!r}",
    ))
    cases.append((
        "ok_row_inserted",
        len(rows) == 1,
        f"got {len(rows)} rows",
    ))

    # ----- 2. 컬럼 매핑 검증 -----
    db = _tmp_db()
    rec = UsageRecorder(db)
    cli = _FakeClient(recorder=rec)
    cli.generate(system_instruction="x", user_text="y", call_site="notify_filter",
                 slug="arca", attempt=3)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    r = conn.execute("SELECT * FROM llm_calls").fetchone()
    cases.append((
        "row_call_site_slug_attempt",
        r["call_site"] == "notify_filter" and r["slug"] == "arca" and r["attempt"] == 3,
        f"got {dict(r)!r}",
    ))
    cases.append((
        "row_status_ok",
        r["status"] == "ok",
        f"got {r['status']!r}",
    ))
    cases.append((
        "row_provider_model",
        r["provider"] == "fake" and r["model"] == "fake-1" and r["raw_model"] == "fake-1-resolved",
        f"got provider={r['provider']!r} model={r['model']!r} raw={r['raw_model']!r}",
    ))

    # ----- 3. 예외 path: 호출 실패해도 recorder 가 status 라벨로 기록 -----
    db = _tmp_db()
    rec = UsageRecorder(db)
    cli = _FakeClient(recorder=rec, raise_exc=LLMQuotaError("boom"))
    raised = False
    try:
        cli.generate(system_instruction="x", user_text="y", call_site="config_generate")
    except LLMQuotaError:
        raised = True
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    r = conn.execute("SELECT * FROM llm_calls").fetchone()
    cases.append((
        "err_quota_recorded",
        raised and r is not None and r["status"] == "quota_429",
        f"raised={raised} row={dict(r) if r else None}",
    ))
    cases.append((
        "err_tokens_zero",
        r["prompt_tokens"] == 0 and r["completion_tokens"] == 0,
        f"got pt={r['prompt_tokens']} ct={r['completion_tokens']}",
    ))

    # ----- 4. 다른 status: http_error -----
    db = _tmp_db()
    rec = UsageRecorder(db)
    cli = _FakeClient(recorder=rec, raise_exc=LLMHttpError("nope", status_code=500))
    try:
        cli.generate(system_instruction="x", user_text="y", call_site="notify_summarize")
    except LLMHttpError:
        pass
    r = sqlite3.connect(db).execute("SELECT status FROM llm_calls").fetchone()
    cases.append((
        "err_http_recorded",
        r is not None and r[0] == "http_error",
        f"got {r!r}",
    ))

    # ----- 5. latency 측정 (sleep 50ms → latency_ms >= 40) -----
    db = _tmp_db()
    rec = UsageRecorder(db)
    cli = _FakeClient(recorder=rec, sleep_s=0.05)
    resp = cli.generate(system_instruction="x", user_text="y", call_site="config_generate")
    cases.append((
        "latency_measured",
        resp.latency_ms >= 40,
        f"got latency_ms={resp.latency_ms}",
    ))

    # ----- 6. cost_fn 주입 시 cost 계산되어 응답·기록 모두 채워짐 -----
    db = _tmp_db()
    rec = UsageRecorder(db)
    def cost_fn(provider, model, pt, ct):
        return pt * 0.001 + ct * 0.01
    cli = _FakeClient(recorder=rec, cost_fn=cost_fn, pt=100, ct=50)
    resp = cli.generate(system_instruction="x", user_text="y", call_site="config_generate")
    expected = 100 * 0.001 + 50 * 0.01
    r = sqlite3.connect(db).execute("SELECT cost_usd FROM llm_calls").fetchone()
    cases.append((
        "cost_computed",
        resp.cost_usd is not None and abs(resp.cost_usd - expected) < 1e-9
        and r is not None and r[0] is not None and abs(r[0] - expected) < 1e-9,
        f"got resp.cost={resp.cost_usd} row.cost={r[0] if r else None}",
    ))

    # ----- 7. recorder 없으면 호출 정상 진행, 예외 없음 -----
    cli = _FakeClient(recorder=None)
    resp = cli.generate(system_instruction="x", user_text="y", call_site="legacy")
    cases.append((
        "no_recorder_ok",
        resp.text == "ok" and resp.total_tokens == 30,
        f"got {resp!r}",
    ))

    # ----- 8. UsageRecorder 가 스키마/인덱스 생성 -----
    db = _tmp_db()
    UsageRecorder(db)
    conn = sqlite3.connect(db)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    idx = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")]
    cases.append((
        "schema_created",
        "llm_calls" in tables and "idx_llm_calls_ts" in idx and "idx_llm_calls_site_ts" in idx,
        f"tables={tables!r} idx={idx!r}",
    ))

    # ----- 9. prices.compute_cost — provider:model 키 우선 -----
    tmp = Path(tempfile.mkdtemp()) / "prices.json"
    tmp.write_text(json.dumps({
        "gemini:gemini-2.5-flash": {"prompt": 0.30, "completion": 2.50, "per": "1M"},
        "gemini-2.5-flash": {"prompt": 999.0, "completion": 999.0, "per": "1M"},  # 덜 specific
    }))
    # cache invalidate 위해 mtime 다르게 — 새 path 라 자동
    c = prices_mod.compute_cost("gemini", "gemini-2.5-flash",
                                prompt_tokens=1_000_000, completion_tokens=1_000_000,
                                prices_path=tmp)
    cases.append((
        "prices_provider_qualified_wins",
        c is not None and abs(c - (0.30 + 2.50)) < 1e-9,
        f"got cost={c}",
    ))

    # ----- 10. prices: missing → None -----
    c = prices_mod.compute_cost("gemini", "no-such-model",
                                prompt_tokens=100, completion_tokens=100,
                                prices_path=tmp)
    cases.append((
        "prices_missing_returns_none",
        c is None,
        f"got cost={c}",
    ))

    # ----- 11. prices: per=1K -----
    tmp2 = Path(tempfile.mkdtemp()) / "prices.json"
    tmp2.write_text(json.dumps({
        "m": {"prompt": 1.0, "completion": 2.0, "per": "1K"},
    }))
    c = prices_mod.compute_cost("any", "m", prompt_tokens=2000, completion_tokens=1000,
                                prices_path=tmp2)
    # 2000 * 1.0 / 1000 + 1000 * 2.0 / 1000 = 2.0 + 2.0 = 4.0
    cases.append((
        "prices_per_1k",
        c is not None and abs(c - 4.0) < 1e-9,
        f"got cost={c}",
    ))

    return cases


if __name__ == "__main__":
    results = run()
    failed = [(n, d) for n, ok, d in results if not ok]
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {d}")
    if failed:
        print(f"\n{len(failed)} FAILED")
        sys.exit(1)
    print(f"\n{len(results)} passed")
