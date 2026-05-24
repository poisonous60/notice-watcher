"""httpx TLS fallback config vocabulary and error classification."""
from __future__ import annotations


covers = ["httpx_tls_fallback"]


def _cfg() -> dict:
    return {
        "version": 1,
        "site": "tls-test",
        "board": "notice",
        "strategy": "httpx_html",
        "list": {
            "url_template": "https://example.go.kr/list.do",
            "tls_fallback": "playwright",
            "row_selector": "tr",
            "fields": {
                "post_id": [{"from": "css", "selector": "a", "attr": "href"}],
                "title": [{"from": "css", "selector": "a", "text": True}],
            },
        },
        "article": {"body_empty_acceptable": True, "content": []},
    }


def run() -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []
    from engine.config_schema import validate_config
    from engine._http import is_tls_transport_error

    try:
        validate_config(_cfg())
        cases.append(("schema_accepts_list_tls_fallback", True, ""))
    except Exception as exc:  # noqa: BLE001
        cases.append(("schema_accepts_list_tls_fallback", False, repr(exc)))

    cases.append(("detects_ssl_handshake",
                  is_tls_transport_error(Exception("SSL: WRONG_VERSION_NUMBER during handshake")),
                  "not detected"))
    cases.append(("ignores_plain_timeout",
                  not is_tls_transport_error(Exception("ReadTimeout")),
                  "misdetected"))
    return cases
