"""routing.json + client_for(call_site) 라우팅 단위 테스트.

- 파일 없음 / 키 없음 → fallback default.
- 파일 변경 → mtime 캐시 갱신.
- override (호출 인자 / process-wide) 우선순위.
- provider 별 client class 매핑.
- (provider, model) 별 인스턴스 캐싱.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


from generate import routing  # noqa: E402
from generate.gemini import GeminiClient  # noqa: E402
from generate.openrouter import OpenRouterClient  # noqa: E402


def _reset_routing_to(path: Path) -> None:
    """테스트 격리: routing 모듈 캐시 클리어 + 경로 override."""
    routing._cache_mtime = -1.0
    routing._cache_table = {}
    routing._client_cache.clear()
    routing._process_override = None
    routing._DEFAULT_ROUTING = path  # type: ignore[attr-defined]
    # _routing_path() 가 _DEFAULT_ROUTING 을 직접 반환하므로 OK


def _tmp_routing(data: dict) -> Path:
    import tempfile
    p = Path(tempfile.mkdtemp()) / "llm_routing.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def run() -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []
    os.environ.setdefault("OPENROUTER_API_KEY", "test-key-for-construction-only")
    os.environ.setdefault("GEMINI_API_KEYS", "test-key-for-construction-only")

    # ----- 1. 파일 없음 → fallback (gemini, default_model()) -----
    _reset_routing_to(Path("/no/such/file/llm_routing.json"))
    cli = routing.client_for("notify_summarize")
    cases.append((
        "fallback_no_file",
        isinstance(cli, GeminiClient),
        f"got {type(cli).__name__}",
    ))

    # ----- 2. 파일 있음, 키 매핑 적용 -----
    p = _tmp_routing({
        "config_generate":  "gemini:gemini-2.5-flash",
        "config_retry":     "gemini:gemini-2.5-pro",
        "notify_summarize": "openrouter:google/gemini-flash-1.5-8b",
        "notify_filter":    "openrouter:google/gemini-flash-1.5-8b",
    })
    _reset_routing_to(p)
    c1 = routing.client_for("config_generate")
    c2 = routing.client_for("config_retry")
    c3 = routing.client_for("notify_summarize")
    cases.append((
        "route_config_generate_gemini",
        isinstance(c1, GeminiClient) and c1.model == "gemini-2.5-flash",
        f"got cls={type(c1).__name__} model={c1.model}",
    ))
    cases.append((
        "route_config_retry_different_model",
        isinstance(c2, GeminiClient) and c2.model == "gemini-2.5-pro",
        f"got cls={type(c2).__name__} model={c2.model}",
    ))
    cases.append((
        "route_notify_summarize_openrouter",
        isinstance(c3, OpenRouterClient) and c3.model == "google/gemini-flash-1.5-8b",
        f"got cls={type(c3).__name__} model={c3.model}",
    ))

    # ----- 3. (provider, model) 인스턴스 캐싱 (같은 키면 같은 인스턴스) -----
    c3b = routing.client_for("notify_filter")  # 같은 openrouter:google/...
    cases.append((
        "instance_cache_shared",
        c3 is c3b,
        f"c3 is c3b: {c3 is c3b}",
    ))

    # ----- 4. _default key fallback -----
    p2 = _tmp_routing({
        "_default": "openrouter:google/gemini-flash-1.5-8b",
        "config_generate": "gemini:gemini-2.5-flash",
    })
    _reset_routing_to(p2)
    c = routing.client_for("notify_summarize")  # 매핑 없음 → _default
    cases.append((
        "default_key_used",
        isinstance(c, OpenRouterClient) and c.model == "google/gemini-flash-1.5-8b",
        f"got cls={type(c).__name__} model={c.model}",
    ))

    # ----- 5. override (호출 인자) — 모든 매핑 우회 -----
    c = routing.client_for("notify_summarize", override="gemini:gemini-2.5-pro")
    cases.append((
        "call_override_wins",
        isinstance(c, GeminiClient) and c.model == "gemini-2.5-pro",
        f"got cls={type(c).__name__} model={c.model}",
    ))

    # ----- 6. process override -----
    routing.set_process_override("openrouter:anthropic/claude-haiku-4-5")
    c = routing.client_for("config_generate")
    cases.append((
        "process_override_wins",
        isinstance(c, OpenRouterClient) and c.model == "anthropic/claude-haiku-4-5",
        f"got cls={type(c).__name__} model={c.model}",
    ))
    routing.set_process_override(None)
    c = routing.client_for("config_generate")
    cases.append((
        "process_override_cleared",
        isinstance(c, GeminiClient) and c.model == "gemini-2.5-flash",
        f"got cls={type(c).__name__} model={c.model}",
    ))

    # ----- 7. mtime cache invalidation — 파일 바뀌면 다음 호출에서 재로드 -----
    p3 = _tmp_routing({"config_generate": "gemini:gemini-2.5-flash"})
    _reset_routing_to(p3)
    c_before = routing.client_for("config_generate")
    # mtime 강제 변경
    time.sleep(0.05)
    p3.write_text(json.dumps({"config_generate": "gemini:gemini-2.5-pro"}), encoding="utf-8")
    os.utime(p3, None)
    c_after = routing.client_for("config_generate")
    cases.append((
        "mtime_reload",
        c_before.model == "gemini-2.5-flash" and c_after.model == "gemini-2.5-pro",
        f"before={c_before.model} after={c_after.model}",
    ))

    # ----- 8. provider 생략 형식 — gemini 로 가정 -----
    p4 = _tmp_routing({"config_generate": "gemini-2.5-flash"})  # provider 빼고
    _reset_routing_to(p4)
    c = routing.client_for("config_generate")
    cases.append((
        "provider_default_gemini",
        isinstance(c, GeminiClient) and c.model == "gemini-2.5-flash",
        f"got cls={type(c).__name__} model={c.model}",
    ))

    # ----- 9. unknown provider → 명확 에러 -----
    p5 = _tmp_routing({"config_generate": "azure:gpt-5"})
    _reset_routing_to(p5)
    raised = False
    try:
        routing.client_for("config_generate")
    except ValueError as e:
        raised = "azure" in str(e)
    cases.append((
        "unknown_provider_errors",
        raised,
        f"raised correctly: {raised}",
    ))

    # ----- 6. sidecar `<call_site>__mode` 파싱 (rev 5 register-agentic) -----
    p6 = _tmp_routing({
        "config_generate": "codex:gpt-5.4-mini#low",
        "config_generate__mode": "agentic",
    })
    _reset_routing_to(p6)
    r6 = routing.resolve("config_generate")
    cases.append((
        "sidecar_mode_agentic",
        r6.provider == "codex" and r6.meta.get("mode") == "agentic",
        f"got provider={r6.provider} meta={dict(r6.meta)}",
    ))

    # ----- 7. sidecar value whitelist 밖 → 무시 -----
    p7 = _tmp_routing({
        "config_generate": "codex:gpt-5.4-mini",
        "config_generate__mode": "weird_value",
    })
    _reset_routing_to(p7)
    r7 = routing.resolve("config_generate")
    cases.append((
        "sidecar_invalid_value_ignored",
        "mode" not in r7.meta,
        f"got meta={dict(r7.meta)}",
    ))

    # ----- 8. sidecar axis 밖 → 무시 -----
    p8 = _tmp_routing({
        "config_generate": "codex:gpt-5.4-mini",
        "config_generate__unknown_axis": "anything",
    })
    _reset_routing_to(p8)
    r8 = routing.resolve("config_generate")
    cases.append((
        "sidecar_unknown_axis_ignored",
        "unknown_axis" not in r8.meta,
        f"got meta={dict(r8.meta)}",
    ))

    # ----- 9. _split_sidecar_key helper -----
    cases.append((
        "split_sidecar_key_valid",
        routing._split_sidecar_key("config_generate__mode") == ("config_generate", "mode"),
        f"got {routing._split_sidecar_key('config_generate__mode')}",
    ))
    cases.append((
        "split_sidecar_key_unknown_axis",
        routing._split_sidecar_key("config_generate__weird") is None,
        f"got {routing._split_sidecar_key('config_generate__weird')}",
    ))
    cases.append((
        "split_sidecar_key_no_double_underscore",
        routing._split_sidecar_key("config_generate") is None,
        f"got {routing._split_sidecar_key('config_generate')}",
    ))

    # ----- 10. dashboard validator: codex+agentic OK, gemini+agentic reject -----
    from dashboard.control_actions import validate_routing as _validate
    cases.append((
        "validator_codex_agentic_ok",
        _validate({"config_generate": "codex:gpt-5.4-mini",
                   "config_generate__mode": "agentic"}) is None,
        "should accept",
    ))
    err_msg = _validate({"config_generate": "gemini:flash",
                         "config_generate__mode": "agentic"})
    cases.append((
        "validator_gemini_agentic_reject",
        err_msg is not None and "provider=codex" in (err_msg or ""),
        f"got err={err_msg!r}",
    ))
    err_msg2 = _validate({"config_generate__mode": "agentic"})
    cases.append((
        "validator_orphan_sidecar_reject",
        err_msg2 is not None,
        f"got err={err_msg2!r}",
    ))
    err_msg3 = _validate({"config_generate": "codex:m",
                          "config_generate__mode": "weird"})
    cases.append((
        "validator_invalid_mode_value_reject",
        err_msg3 is not None and "허용 값" in (err_msg3 or ""),
        f"got err={err_msg3!r}",
    ))

    # cleanup
    _reset_routing_to(Path("/no/such/file"))

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
