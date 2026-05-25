"""register.py auto mode dispatch tests (offline monkeypatch).

Checks only the routing/decision wiring:
- auto success after api_loop_once never calls agentic
- auto api_loop_once decisive content failure becomes REJECTED rc=3
- auto non-decisive failure calls agentic with a compact failure packet
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from generate import GenerationError  # noqa: E402


def _load_register():
    rp = Path(__file__).resolve().parent.parent.parent / "scripts" / "register.py"
    spec = importlib.util.spec_from_file_location("reg_auto_under_test", rp)
    reg = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(reg)
    return reg


class _NoopSpan:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def set_attr(self, key, value):
        pass


class _NoopTrace:
    def span(self, name, attrs=None):
        return _NoopSpan()


def _patch_agentic_success(reg, monkeypatch):
    calls: list[dict] = []

    async def fake_run_agentic(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            config={"agentic": True},
            report=SimpleNamespace(ok=True),
            stop_reason="validate_pass",
            wall_s=1.0,
            prompt_tokens=1,
            completion_tokens=2,
            codex_version="codex-cli test",
        )

    class FakeRecorder:
        def write(self, **kw):
            pass

    monkeypatch.setattr(reg, "_run_codex_agentic", fake_run_agentic)
    monkeypatch.setattr(reg, "_get_default_recorder", lambda: FakeRecorder())
    monkeypatch.setattr(reg, "_compute_cost", lambda *a, **k: 0.0)
    monkeypatch.setattr(reg, "current_trace", lambda: _NoopTrace())
    return calls


def test_gen_agentic_uses_default_timeout_without_wall_deadline(monkeypatch):
    reg = _load_register()
    calls = _patch_agentic_success(reg, monkeypatch)

    cfg, rep = reg._gen_agentic(
        {"url": "https://example.com/default"},
        "slugdefault",
        "https://example.com/default",
        wall_deadline=None,
    )

    assert cfg == {"agentic": True}
    assert getattr(rep, "ok", False) is True
    assert calls[0]["timeout_s"] == reg.DEFAULT_AGENTIC_TIMEOUT_S


def test_gen_agentic_caps_timeout_to_remaining_wall_budget(monkeypatch):
    reg = _load_register()
    calls = _patch_agentic_success(reg, monkeypatch)
    monkeypatch.setattr(reg.time, "monotonic", lambda: 100.0)

    reg._gen_agentic(
        {"url": "https://example.com/tight"},
        "slugtight",
        "https://example.com/tight",
        wall_deadline=170.0,
    )

    assert calls[0]["timeout_s"] == 60.0


def test_gen_agentic_rejects_too_small_remaining_wall_budget(monkeypatch):
    reg = _load_register()
    _patch_agentic_success(reg, monkeypatch)
    monkeypatch.setattr(reg.time, "monotonic", lambda: 100.0)

    try:
        reg._gen_agentic(
            {"url": "https://example.com/expired"},
            "slugexpired",
            "https://example.com/expired",
            wall_deadline=135.0,
        )
    except reg.RegisterTimeoutError:
        return
    raise AssertionError("expected RegisterTimeoutError")


def run() -> list[tuple[str, bool, str]]:
    reg = _load_register()
    cases: list[tuple[str, bool, str]] = []

    args = SimpleNamespace(model=None)
    route_auto = SimpleNamespace(provider="codex", meta={"mode": "auto"})
    route_api = SimpleNamespace(provider="codex", meta={})
    route_agentic = SimpleNamespace(provider="codex", meta={"mode": "agentic"})
    route_gemini_auto = SimpleNamespace(provider="gemini", meta={"mode": "auto"})

    cases.append(("mode_default_api_loop",
                  reg._select_generation_mode(route_api, args) == "api_loop",
                  ""))
    cases.append(("mode_agentic",
                  reg._select_generation_mode(route_agentic, args) == "agentic",
                  ""))
    cases.append(("mode_auto",
                  reg._select_generation_mode(route_auto, args) == "auto",
                  ""))
    cases.append(("mode_auto_non_codex_fails_closed",
                  reg._select_generation_mode(route_gemini_auto, args) == "api_loop",
                  ""))
    cases.append(("mode_model_override_forces_api_loop",
                  reg._select_generation_mode(route_auto, SimpleNamespace(model="gemini-x")) == "api_loop",
                  ""))

    calls: list[tuple] = []

    def fake_gen(digest, *, max_attempts, model):
        calls.append(("gen", max_attempts, model))
        return {"ok": True}, SimpleNamespace(ok=True)

    def fake_agentic(digest, slug, url, failure_packet=None):
        calls.append(("agentic", failure_packet))
        return {"agentic": True}, SimpleNamespace(ok=True)

    cfg, rep = reg._generate_by_mode(
        "auto", {"url": "https://example.com/board"}, "slug", "https://example.com/board",
        max_attempts=4, model=None, gen_func=fake_gen, agentic_func=fake_agentic,
    )
    cases.append(("auto_success_uses_one_attempt",
                  cfg == {"ok": True} and getattr(rep, "ok", False) is True and calls == [("gen", 1, None)],
                  f"calls={calls}"))

    err = GenerationError("one-shot failed")
    err.last_config = {"strategy": "httpx_html"}
    err.last_feedback = "[FAIL] posts_nonempty: 0 rows"
    calls.clear()
    saved: list[tuple] = []
    orig_classify = reg._classify_veto
    orig_save = reg._save_rejected
    reg._classify_veto = lambda digest, url, slug, gate_only: {
        "class": "content", "confidence": 0.9, "reason": "single article"
    }
    reg._save_rejected = lambda *a, **k: saved.append((a, k))
    try:
        rc = reg._generation_failure_reject_rc({"url": "u"}, "u", "s", err, gate_only=False)
    finally:
        reg._classify_veto = orig_classify
        reg._save_rejected = orig_save
    cases.append(("auto_content_fail_rejected",
                  rc == 3 and len(saved) == 1 and saved[0][1].get("learn") is False,
                  f"rc={rc} saved={saved}"))

    def failing_gen(digest, *, max_attempts, model):
        calls.append(("gen", max_attempts, model))
        raise err

    def agentic_after_fail(digest, slug, url, failure_packet=None):
        calls.append(("agentic", failure_packet))
        return {"agentic": True}, SimpleNamespace(ok=True)

    calls.clear()
    orig_reject = reg._generation_failure_reject_rc
    reg._generation_failure_reject_rc = (
        lambda digest, url, slug, exc, gate_only=False, include_heterogeneous_hub=True: None
    )
    try:
        cfg2, rep2 = reg._generate_by_mode(
            "auto", {"url": "https://example.com/board"}, "slug", "https://example.com/board",
            max_attempts=4, model=None, gen_func=failing_gen, agentic_func=agentic_after_fail,
        )
    finally:
        reg._generation_failure_reject_rc = orig_reject
    packet = calls[1][1] if len(calls) > 1 else None
    cases.append(("auto_failure_packet_to_agentic",
                  cfg2 == {"agentic": True}
                  and getattr(rep2, "ok", False) is True
                  and calls[0] == ("gen", 1, None)
                  and calls[1][0] == "agentic"
                  and packet["source"] == "api_loop_once"
                  and packet["candidate_config"] == {"strategy": "httpx_html"}
                  and "posts_nonempty" in packet["validation_feedback"],
                  f"calls={calls} packet={packet}"))

    # auto one-shot should not use the older heterogeneous-hub postmortem gate.
    # Non-decisive classifier means the hard case should still get agentic.
    calls.clear()
    orig_reject = reg._generation_failure_reject_rc
    orig_hub = reg._heterogeneous_hub_check
    orig_classify = reg._classify_veto
    reg._classify_veto = lambda digest, url, slug, gate_only: {
        "class": "?", "confidence": 0.0, "reason": "uncertain"
    }
    reg._heterogeneous_hub_check = lambda digest, url: "hub-like"
    try:
        cfg3, _ = reg._generate_by_mode(
            "auto", {"url": "https://example.com/hub"}, "slug", "https://example.com/hub",
            max_attempts=4, model=None, gen_func=failing_gen, agentic_func=agentic_after_fail,
        )
    finally:
        reg._generation_failure_reject_rc = orig_reject
        reg._heterogeneous_hub_check = orig_hub
        reg._classify_veto = orig_classify
    cases.append(("auto_uncertain_hub_still_agentic",
                  cfg3 == {"agentic": True} and calls[1][0] == "agentic",
                  f"calls={calls}"))

    # Agentic runs bypass LLMClient.generate(), so register.py must explicitly
    # write usage.sqlite3 rows and timing attrs for dashboard observability.
    class FakeRecorder:
        def __init__(self):
            self.rows = []

        def write(self, **kw):
            self.rows.append(kw)

    class FakeSpan:
        def __init__(self, name, attrs):
            self.name = name
            self.attrs = dict(attrs or {})

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.attrs["ok"] = exc_type is None
            if exc_type is not None:
                self.attrs["err_type"] = exc_type.__name__

        def set_attr(self, key, value):
            self.attrs[key] = value

    class FakeTrace:
        def __init__(self):
            self.spans = []

        def span(self, name, attrs=None):
            sp = FakeSpan(name, attrs)
            self.spans.append(sp)
            return sp

    async def fake_run_agentic(**kwargs):
        return SimpleNamespace(
            config={"agentic": True},
            report=SimpleNamespace(ok=True),
            stop_reason="validate_pass",
            wall_s=12.5,
            prompt_tokens=123,
            completion_tokens=7,
            codex_version="codex-cli test",
        )

    rec = FakeRecorder()
    trace = FakeTrace()
    orig_run_agentic = reg._run_codex_agentic
    orig_recorder = reg._get_default_recorder
    orig_cost = reg._compute_cost
    orig_trace = reg.current_trace
    orig_route = reg._resolve_route
    reg._run_codex_agentic = fake_run_agentic
    reg._get_default_recorder = lambda: rec
    reg._compute_cost = lambda provider, model, prompt_tokens, completion_tokens: 0.001
    reg.current_trace = lambda: trace
    reg._resolve_route = lambda call_site: SimpleNamespace(model="gpt-5.4-mini")
    try:
        cfg4, rep4 = reg._gen_agentic(
            {"url": "https://example.com/hard"},
            "slughard",
            "https://example.com/hard",
            failure_packet={"source": "api_loop_once"},
        )
    finally:
        reg._run_codex_agentic = orig_run_agentic
        reg._get_default_recorder = orig_recorder
        reg._compute_cost = orig_cost
        reg.current_trace = orig_trace
        reg._resolve_route = orig_route
    row = rec.rows[0] if rec.rows else {}
    span = trace.spans[0] if trace.spans else None
    cases.append(("agentic_usage_recorded",
                  cfg4 == {"agentic": True}
                  and getattr(rep4, "ok", False) is True
                  and row.get("call_site") == "config_generate_agentic"
                  and row.get("slug") == "slughard"
                  and row.get("provider") == "codex"
                  and row.get("raw_model") == "gpt-5.4-mini"
                  and row.get("status") == "ok"
                  and row.get("prompt_tokens") == 123
                  and row.get("completion_tokens") == 7
                  and row.get("total_tokens") == 130
                  and row.get("latency_ms") == 12500,
                  f"row={row}"))
    cases.append(("agentic_timing_span_attrs",
                  span is not None
                  and span.name == "codex_agentic_generate"
                  and span.attrs.get("auto_escalated") is True
                  and span.attrs.get("prompt_tokens") == 123
                  and span.attrs.get("completion_tokens") == 7
                  and span.attrs.get("stop_reason") == "validate_pass"
                  and span.attrs.get("codex_version") == "codex-cli test",
                  f"span={None if span is None else (span.name, span.attrs)}"))

    async def fake_run_agentic_fail(**kwargs):
        raise reg._AgenticGenerationError(
            "agent gave up",
            last_config={"bad": True},
            last_feedback="still failing",
            prompt_tokens=456,
            completion_tokens=8,
            wall_s=20.0,
            stop_reason="max_cycles",
            codex_version="codex-cli fail",
        )

    rec_fail = FakeRecorder()
    trace_fail = FakeTrace()
    orig_run_agentic = reg._run_codex_agentic
    orig_recorder = reg._get_default_recorder
    orig_trace = reg.current_trace
    reg._run_codex_agentic = fake_run_agentic_fail
    reg._get_default_recorder = lambda: rec_fail
    reg.current_trace = lambda: trace_fail
    translated = None
    try:
        try:
            reg._gen_agentic({"url": "https://example.com/fail"},
                             "slugfail", "https://example.com/fail")
        except GenerationError as e:
            translated = e
    finally:
        reg._run_codex_agentic = orig_run_agentic
        reg._get_default_recorder = orig_recorder
        reg.current_trace = orig_trace
    fail_row = rec_fail.rows[0] if rec_fail.rows else {}
    fail_span = trace_fail.spans[0] if trace_fail.spans else None
    cases.append(("agentic_failure_usage_recorded",
                  translated is not None
                  and getattr(translated, "prompt_tokens", None) == 456
                  and fail_row.get("call_site") == "config_generate_agentic"
                  and fail_row.get("status") == "other"
                  and fail_row.get("total_tokens") == 464
                  and fail_row.get("latency_ms") == 20000,
                  f"translated={translated} row={fail_row}"))
    cases.append(("agentic_failure_timing_attrs",
                  fail_span is not None
                  and fail_span.attrs.get("ok") is False
                  and fail_span.attrs.get("prompt_tokens") == 456
                  and fail_span.attrs.get("completion_tokens") == 8
                  and fail_span.attrs.get("stop_reason") == "max_cycles"
                  and fail_span.attrs.get("codex_version") == "codex-cli fail",
                  f"span={None if fail_span is None else (fail_span.name, fail_span.attrs)}"))

    return cases


if __name__ == "__main__":
    results = run()
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {d}")
    failed = [r for r in results if not r[1]]
    if failed:
        print(f"\n{len(failed)} FAILED")
        sys.exit(1)
    print(f"\n{len(results)} passed")
