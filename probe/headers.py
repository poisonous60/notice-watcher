"""HTTP 헤더 프리셋과 캡처 헤더 합성.

H1~H4는 사이트 무관 일반 프리셋. H_capture는 Phase 2 Playwright 실행 중
메인 문서 요청에서 자동 캡처되는 헤더(`captured_headers.json`)에서 합성된다.
"""
from __future__ import annotations

from urllib.parse import urlsplit


_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Mobile Safari/537.36"
)


def preset_h1_bare() -> dict[str, str]:
    return {}


def preset_h2_chrome_min() -> dict[str, str]:
    return {"User-Agent": _DESKTOP_UA}


def preset_h3_chrome_full() -> dict[str, str]:
    return {
        "User-Agent": _DESKTOP_UA,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }


def preset_h4_chrome_full_referer(url: str) -> dict[str, str]:
    headers = preset_h3_chrome_full()
    parts = urlsplit(url)
    headers["Referer"] = f"{parts.scheme}://{parts.netloc}/"
    return headers


def preset_h5_mobile_chrome(url: str) -> dict[str, str]:
    parts = urlsplit(url)
    return {
        "User-Agent": _MOBILE_UA,
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": f"{parts.scheme}://{parts.netloc}/",
        "sec-ch-ua-mobile": "?1",
    }


def merge_captured(captured: dict[str, str]) -> dict[str, str]:
    """Playwright가 캡처한 메인 문서 헤더를 httpx가 받아들이는 형태로 정리.

    httpx가 자체 관리하는 :authority, :method, :path, :scheme 등 pseudo-header,
    그리고 Host/Content-Length/Connection처럼 변경하면 안 되는 헤더는 제외.
    """
    drop = {
        ":authority", ":method", ":path", ":scheme",
        "host", "content-length", "connection",
        # httpx가 자동 처리
        "accept-encoding",
    }
    out: dict[str, str] = {}
    for k, v in captured.items():
        if not k:
            continue
        if k.lower() in drop:
            continue
        out[k] = v
    return out


def all_presets(url: str) -> dict[str, dict[str, str]]:
    return {
        "H1": preset_h1_bare(),
        "H2": preset_h2_chrome_min(),
        "H3": preset_h3_chrome_full(),
        "H4": preset_h4_chrome_full_referer(url),
    }
