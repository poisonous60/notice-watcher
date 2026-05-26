"""engine.cf_state_cache — CF verdict 영구 캐시 (slug 단위 JSON, TTL 7일)."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def run() -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []
    td = tempfile.mkdtemp()
    cache_path = Path(td) / "cf_state.json"
    os.environ["NW_CF_STATE_PATH"] = str(cache_path)

    # import + override _CACHE_PATH explicitly (env may have been loaded before this call)
    from engine import cf_state_cache as c
    c._CACHE_PATH = cache_path
    c._cache = None

    cases.append(("empty_returns_none", c.get("foo") is None, "expected None"))

    c.put("host_pubg__news", "cleared")
    cases.append(("put_get_roundtrip", c.get("host_pubg__news") == "cleared",
                  f"got {c.get('host_pubg__news')!r}"))

    c.put("host_x", "invalid_state")
    cases.append(("invalid_state_rejected", c.get("host_x") is None,
                  f"got {c.get('host_x')!r}"))

    # persist after _cache reset (file-read)
    c._cache = None
    cases.append(("persists_after_reset", c.get("host_pubg__news") == "cleared",
                  f"got {c.get('host_pubg__news')!r}"))

    # TTL stale (file manipulation)
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    data["states"]["host_pubg__news"]["ts"] = "2020-01-01T00:00:00+00:00"
    cache_path.write_text(json.dumps(data), encoding="utf-8")
    c._cache = None
    cases.append(("ttl_stale_returns_none", c.get("host_pubg__news") is None,
                  f"got {c.get('host_pubg__news')!r}"))

    # valid 4 verdicts
    for v in ("none", "cleared", "turnstile", "timeout"):
        c.put(f"host_{v}", v)
        cases.append((f"verdict_{v}_roundtrip", c.get(f"host_{v}") == v,
                      f"got {c.get(f'host_{v}')!r}"))

    # empty/None key guard
    cases.append(("empty_key_put_noop", (c.put("", "cleared") or True),
                  "put('') should not raise"))
    cases.append(("empty_key_get_none", c.get("") is None, "empty key returns None"))

    return cases
