"""응답 분류 (OK / BLOCKED_BOT / BLOCKED_IP / BLOCKED_GEO / LOGIN_REQUIRED / NOT_FOUND / METHOD_INCOMPATIBLE / UNKNOWN_ERROR)."""
from __future__ import annotations

import re
from typing import Optional

from .types import Classification


_LOGIN_REDIRECT_RE = re.compile(r"(/login|/signin|/sign-in|/auth/login|/users?/login)", re.IGNORECASE)
# 본문 마커는 페이지 *전체*가 로그인 안내일 때만 LOGIN_REQUIRED로 판정한다.
# (디시처럼 평범한 UI 문구로 "로그인이 필요합니다." 가 들어 있는 경우와 구별하려고
#  본문이 매우 짧을 때만 인정하거나, 강한 시그널 키워드만 사용)
_LOGIN_BODY_MARKERS_STRONG = (
    "please log in to view",
    "you must be logged in to view",
    "this page requires login",
    "로그인 후 이용 가능",
    "로그인 후 확인",
    "로그인이 필요한 서비스",
    "로그인 후 이용해 주세요",
)
_LOGIN_BODY_MARKERS_WEAK = (
    "please log in",
    "please sign in",
    "sign in to view",
    "you must be logged in",
    "로그인이 필요",
    "로그인 후 이용",
)
_LOGIN_FORM_RE = re.compile(
    r'<input[^>]+type=["\']password["\']|<form[^>]+action=["\'][^"\']*(login|signin)',
    re.IGNORECASE,
)

# 강한 마커: 본문에 들어 있으면 거의 확실히 봇 차단 페이지
_BOT_BODY_MARKERS_STRONG = (
    "Just a moment",
    "cf-chl-opt",
    "challenge-platform",
    "비정상적인 접근",
    "차단되었습니다",
    "Attention Required",
    "Cloudflare Ray ID",
    "Please complete the security check",
)
# 약한 마커: 단독으로는 분류 근거 부족. 4xx/5xx 또는 짧은 본문과 결합되어야 함.
_BOT_BODY_MARKERS_WEAK = (
    "Too Many Requests",
    "Rate limit exceeded",
    "Access denied",
    "blocked",
)

_GEO_BODY_MARKERS = (
    "Unavailable For Legal Reasons",
    "이 채널은 한국",
    "지역에서 이용",
    "available in your country",
    "not available in your region",
)

# inline <script>/<style> 안 문자열 (alert 메시지·i18n 사전·주석 등) 이 콘텐츠 마커로 잘못
# 매치되는 경우가 흔하다 (예: NCS 의 fn_layerNcsS_loginCheck() 내 alert("로그인이 필요한 서비스...")).
# marker 검사 전에 한 번 제거하고 visible text 로만 본다.
_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style|noscript)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE
)


def _strip_scripts(s: str) -> str:
    return _SCRIPT_STYLE_RE.sub("", s)


def classify(
    *,
    status: Optional[int],
    body: Optional[str],
    headers: Optional[dict[str, str]],
    final_url: Optional[str] = None,
    redirected_to_login: bool = False,
    error: Optional[str] = None,
    baseline_blocked: bool = False,
    is_method_incompatible: bool = False,
    is_robots_txt: bool = False,
) -> tuple[Classification, list[str]]:
    """단일 응답을 분류한다. notable[]에 감지된 신호 메시지를 함께 반환."""
    notable: list[str] = []

    if is_method_incompatible:
        notable.append("method-incompatible (lib limit or skipped)")
        return Classification.METHOD_INCOMPATIBLE, notable

    if error:
        notable.append(f"error: {error}")
        if status is None:
            return Classification.UNKNOWN_ERROR, notable

    headers_lower = {k.lower(): v for k, v in (headers or {}).items()}
    body_text = body or ""
    visible_text = _strip_scripts(body_text)
    body_short_lc = visible_text[:8000].lower()

    # 1) LOGIN_REQUIRED — 페이지 전체가 로그인을 강요할 때만
    if redirected_to_login or (final_url and _LOGIN_REDIRECT_RE.search(final_url)):
        notable.append("redirected to login")
        return Classification.LOGIN_REQUIRED, notable
    # 강한 마커: 거의 확실한 로그인 페이지 (visible text — inline JS/CSS 제외)
    if any(m in visible_text.lower() for m in (s.lower() for s in _LOGIN_BODY_MARKERS_STRONG)):
        notable.append("strong login marker in body")
        return Classification.LOGIN_REQUIRED, notable
    # 약한 마커: 본문이 짧을 때만 (페이지 전체가 안내문 한 줄)
    if any(m in visible_text for m in _LOGIN_BODY_MARKERS_WEAK) and len(visible_text) < 4000:
        notable.append("weak login marker + short body")
        return Classification.LOGIN_REQUIRED, notable
    # 로그인 form / password input — 본문이 짧을 때만 (메인 콘텐츠 페이지에 검색 form 등이 우연히 매치되는 경우 방지)
    if _LOGIN_FORM_RE.search(visible_text) and len(visible_text) < 6000:
        notable.append("login form + short body")
        return Classification.LOGIN_REQUIRED, notable

    # 2) NOT_FOUND
    if status == 404:
        return Classification.NOT_FOUND, notable

    # 3) BLOCKED_GEO
    if status == 451:
        notable.append("HTTP 451 Unavailable For Legal Reasons")
        return Classification.BLOCKED_GEO, notable
    if any(m in visible_text for m in _GEO_BODY_MARKERS):
        notable.append("geo block marker in body")
        return Classification.BLOCKED_GEO, notable

    # 4) BLOCKED_BOT
    bot_signal = False
    bad_status = status in (403, 429, 503)
    if bad_status:
        bot_signal = True
        notable.append(f"status {status}")
    if "cf-mitigated" in headers_lower:
        bot_signal = True
        notable.append(f"cf-mitigated: {headers_lower['cf-mitigated']}")
    if "retry-after" in headers_lower:
        bot_signal = True
        notable.append(f"Retry-After: {headers_lower['retry-after']}")
    # 강한 마커: 단독으로 충분
    for marker in _BOT_BODY_MARKERS_STRONG:
        if marker.lower() in body_short_lc:
            bot_signal = True
            notable.append(f"strong bot marker: {marker}")
            break
    # 약한 마커: bad_status 또는 짧은 본문과 결합되어야 분류 근거
    if not bot_signal:
        for marker in _BOT_BODY_MARKERS_WEAK:
            if marker.lower() in body_short_lc and (bad_status or len(visible_text) < 4000):
                bot_signal = True
                notable.append(f"weak bot marker + bad context: {marker}")
                break

    if bot_signal:
        # BLOCKED_IP는 baseline까지 같이 막혔을 때만
        if baseline_blocked and status and status >= 400:
            notable.append("baseline also blocked → IP-level")
            return Classification.BLOCKED_IP, notable
        return Classification.BLOCKED_BOT, notable

    # 5) OK
    if status is not None and 200 <= status < 400:
        # robots.txt 는 원래 짧다 (수십~수백 바이트가 정상) — size 임계 적용 X
        if is_robots_txt:
            return Classification.OK, notable
        # UA/헤더 필터로 빈 응답을 받은 경우 (디시는 헤더 없으면 0 bytes 반환) → 봇 차단으로 처리
        if len(body_text) < 200:
            notable.append(f"suspiciously empty body ({len(body_text)} bytes) — UA/header filter suspected")
            return Classification.BLOCKED_BOT, notable
        if len(body_text) < 1500:
            notable.append(f"short body ({len(body_text)} bytes) — possible SPA shell")
        return Classification.OK, notable

    # 6) IP-level fallback
    if status and status >= 400 and baseline_blocked:
        return Classification.BLOCKED_IP, notable

    return Classification.UNKNOWN_ERROR, notable
