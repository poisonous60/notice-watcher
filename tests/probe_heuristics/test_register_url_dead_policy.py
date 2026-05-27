"""register url_dead policy gates for cross-host redirects and probe timeout baselines."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


covers = ["register_cross_host_redirect_url_dead", "register_probe_timeout_host_dead"]


def run() -> list[tuple[str, bool, str]]:
    from scripts import register

    cases: list[tuple[str, bool, str]] = []

    digest = {
        "verdict": "CROSS_HOST_REDIRECT / static ok",
        "entry_matrix": [
            {"target": "list", "classification": "OK"},
        ],
    }
    ok, msgs = register._policy_check(digest, "https://slaythespire.com/news/")
    cases.append(("cross_host_redirect_policy_rejects_even_with_ok_entry",
                  ok is False and any("redirect" in m.lower() for m in msgs),
                  f"ok={ok} msgs={msgs}"))

    class FakeHTTPX:
        class ConnectTimeout(Exception):
            pass

        class ConnectError(Exception):
            pass

        class ReadTimeout(Exception):
            pass

        class RemoteProtocolError(Exception):
            pass

        class Client:
            def __init__(self, timeout: float, follow_redirects: bool):
                self.timeout = timeout
                self.follow_redirects = follow_redirects

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def head(self, url: str):
                raise FakeHTTPX.ConnectTimeout("tcp connect timed out")

    reason = register._probe_timeout_host_dead_reason(
        "https://hadesgame.com/news/",
        httpx_module=FakeHTTPX,
    )
    cases.append(("probe_timeout_dead_baseline_gets_reason",
                  bool(reason and "tcp connect timed out" in reason),
                  str(reason)))

    class LiveHTTPX(FakeHTTPX):
        class Client(FakeHTTPX.Client):
            def head(self, url: str):
                return object()

    live_reason = register._probe_timeout_host_dead_reason(
        "https://example.com/news/",
        httpx_module=LiveHTTPX,
    )
    cases.append(("probe_timeout_live_baseline_no_reason",
                  live_reason is None,
                  str(live_reason)))

    return cases


if __name__ == "__main__":
    failed = [(n, m) for n, ok, m in run() if not ok]
    if failed:
        raise SystemExit(failed)
