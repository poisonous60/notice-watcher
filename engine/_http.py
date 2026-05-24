"""Shared httpx helpers for declarative strategies."""
from __future__ import annotations

import ssl
from typing import Any

import httpx


_TLS_ERROR_MARKERS = (
    "SSL",
    "TLS",
    "WRONG_VERSION_NUMBER",
    "SSLV3_ALERT_HANDSHAKE_FAILURE",
    "UNSAFE_LEGACY_RENEGOTIATION_DISABLED",
    "CERTIFICATE_VERIFY_FAILED",
    "EOF occurred in violation of protocol",
    "Connection reset by peer",
)


def is_tls_transport_error(exc: BaseException) -> bool:
    text = " ".join(str(x) for x in (exc, getattr(exc, "__cause__", ""), getattr(exc, "__context__", "")))
    return any(marker in text for marker in _TLS_ERROR_MARKERS)


def legacy_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if hasattr(ssl, "OP_LEGACY_SERVER_CONNECT"):
        ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
    return ctx


def build_async_client(cfg: dict, **overrides: Any) -> httpx.AsyncClient:
    kwargs: dict[str, Any] = {
        "headers": cfg.get("headers") or {},
        "timeout": float(cfg.get("timeout", 15.0)),
        "follow_redirects": True,
    }
    kwargs.update(overrides)
    return httpx.AsyncClient(**kwargs)


async def get_with_tls_fallback(adapter, url: str, *, scope: str = "list") -> httpx.Response:
    cfg = adapter.cfg
    client = getattr(adapter, "_client", None)
    try:
        if client is not None:
            return await client.get(url)
        async with build_async_client(cfg) as c:
            return await c.get(url)
    except Exception as exc:
        if not is_tls_transport_error(exc):
            raise
        section = cfg.get(scope) if isinstance(cfg.get(scope), dict) else {}
        mode = (section or {}).get("tls_fallback") or "none"
        if mode == "playwright":
            raise RuntimeError(
                f"{adapter.site} {scope}: httpx TLS handshake failed; "
                "config requests list.tls_fallback='playwright', use strategy='playwright_html'"
            ) from exc
        # Last low-risk retry for legacy KR public-sector TLS stacks. It keeps certificate
        # verification enabled, but permits OpenSSL's legacy server-connect option when present.
        async with build_async_client(cfg, verify=legacy_ssl_context()) as c:
            return await c.get(url)
