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
