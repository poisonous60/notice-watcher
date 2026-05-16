"""probe.diagnose._is_cert_or_dns_error + CERT_OR_DNS_BROKEN verdict.

regression: 2026-05-16 — standardsuniversity.org 의 SSL Hostname mismatch 가
BASELINE_BLOCKED 로 뭉뚱그려져서 register 메시지가 "차단(BLOCKED) 사이트로 보임"
이라고 잘못 안내. cert/dns 오류는 BLOCKED 아니므로 별도 verdict 로 분리.
"""
from __future__ import annotations


covers = ["diagnose_cert_or_dns_verdict"]


def run() -> list[tuple[str, bool, str]]:
    from probe.diagnose import _is_cert_or_dns_error

    cases: list[tuple[str, bool, str]] = []

    # 1. httpx SSL hostname mismatch
    err = ("ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
           "Hostname mismatch, certificate is not valid for 'www.standardsuniversity.org'. (_ssl.c:1032)")
    cases.append(("httpx_cert_hostname_mismatch", _is_cert_or_dns_error(err), err))

    # 2. Playwright cert common name invalid
    err2 = ("Error: Page.goto: net::ERR_CERT_COMMON_NAME_INVALID at "
            "https://www.standardsuniversity.org/...")
    cases.append(("playwright_cert_common_name", _is_cert_or_dns_error(err2), err2))

    # 3. DNS resolution 실패
    err3 = "ConnectError: [Errno -2] Name or service not known"
    cases.append(("dns_getaddrinfo_failed", _is_cert_or_dns_error(err3), err3))

    # 4. 403 같은 일반 차단 에러는 False
    err4 = "HTTPStatusError: 403 Forbidden"
    cases.append(("normal_http_error_not_cert", not _is_cert_or_dns_error(err4), err4))

    # 5. None / 빈 문자열 → False
    cases.append(("none_error_handled", not _is_cert_or_dns_error(None), "None"))
    cases.append(("empty_error_handled", not _is_cert_or_dns_error(""), "''"))

    return cases
