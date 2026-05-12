"""probe 전단 URL 게이트 — 봇이 처음 보는 사이트를 /watch·/preview 할 때, register.py(→probe)
를 띄우기 *전에* URL 이 적절한지 검사한다.

스테이지 (순서대로, 하나라도 막히면 UrlRejected):
  1) 구조 검증   — stdlib urllib.parse 만. http/https / hostname 존재 / user:pass@ 없음 /
                   공백·제어문자 없음 / host 가 IP 리터럴(공인·사설·IPv6) 이면 거부.
  2) 정책 블랙리스트 (네트워크 X) — bot/url_blacklist.json 의 그룹별 host_suffix / path_ext 에 걸리면
                   그 그룹의 message 로 거부(기본 그룹: SNS·동영상 호스트 / 축약 링크 호스트 / 파일 직링 .pdf·.zip…).
                   파일이 없거나 깨지면 내장 기본값(_DEFAULT_BLACKLIST) 사용 — blacklist_status() 로 확인.
  3) SSRF       — host 를 IDNA 인코딩해 DNS 해석, 해석된 *모든* IP 가 사설/loopback/link-local/
                   reserved/multicast/unspecified 중 하나면 거부. (gaierror → dns_failed)
  4) Safe Browsing — Google Safe Browsing v4 threatMatches:find 한 번 호출(POST, 4s, 재시도 X). **fail-closed**:
                   키 미설정·네트워크 오류·non-200·JSON 파싱 실패 → gsb_error 거부.
                   응답에 matches 가 있으면 → malicious 거부. 빈 응답({}) 이면 통과.
                   (v5 urls:search 는 JSON 을 안 주고 protobuf 만 줘서 v4 를 쓴다 — v4 는 2027-03-31 종료 예정,
                    그땐 is_url_safe() 만 v5(protobuf) 또는 Web Risk 로 갈아끼우면 된다.)

호출: `await url_gate.check(url, article_url=...)` (bot/main.py 의 _ensure_registered 안에서, async).
       단독 실행: `python -m bot.url_gate "<url>" [--article-url <url>] [--no-gsb] [--no-dns]`

거부 통계: in-process 24h 슬라이딩 카운터(`rejection_summary_24h()`) — 봇 재시작 시 리셋. /status 가 읽음.

키: .env 의 SAFE_BROWSING_API_KEY (bot/config.py). 없으면 4) 가 fail-closed 로 모든 신규 등록을 거부하므로
    봇 on_ready 에서 경고 로그를 띄운다. 발급: GCP 콘솔 → Safe Browsing API 사용 설정 → API 키 생성 →
    그 키를 Safe Browsing API 로만 제한(권장).

블랙리스트 설정: bot/url_blacklist.json — {"groups": [{"name", "message", "host_suffix": [], "path_ext": []}, ...]}.
    위에서부터 검사, 첫 매치의 message 로 거부, name 은 /status 거부 카운터 키. host_suffix 는 'youtube.com'(점 없이),
    path_ext 는 '.pdf' 형태(점은 있어도 없어도 됨). 둘 다 선택이지만 그룹당 적어도 하나. 편집하면 다음 검사 때 자동 반영
    (mtime 감지, 재시작 불필요). 파일이 없거나 JSON/스키마가 깨지면 url_gate.py 의 _DEFAULT_BLACKLIST 로 폴백(봇은 안 죽음).

알려진 한계: 게이트는 제출된 URL 문자열 그대로만 본다 — 301 리다이렉트(→SNS / →사설 IP)나 DNS rebinding
    (TOCTOU) 은 완전히 막지 못한다(probe 의 baseline 이 최종 URL 을 다시 classify 하긴 함). DNS 가 hang
    하면 getaddrinfo 가 asyncio 기본 executor 스레드를 OS 리졸버 타임아웃만큼 점유할 수 있다(여기선 5s 로 await 만 끊음).
    Safe Browsing 은 v4 threatMatches:find 를 쓴다(v5 urls:search 는 protobuf 만 줌). v4 종료(2027-03-31) 전까진
    is_url_safe() 만 갈아끼우면 v5/Web Risk 로 옮길 수 있다.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import socket
import sys
import time
from collections import deque
from pathlib import Path
from typing import Callable, NoReturn, Optional
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from bot.config import safe_browsing_api_key  # noqa: E402

log = logging.getLogger("bot.url_gate")


# --------------------------------------------------------------------------- #
# 예외
# --------------------------------------------------------------------------- #
class UrlRejected(Exception):
    """게이트가 URL 을 거부. reason = 머신 키(카운터 버킷용), msg = 사용자에게 보여줄 한국어 문장."""

    def __init__(self, reason: str, msg: str):
        super().__init__(f"{reason}: {msg}")
        self.reason = reason
        self.msg = msg


class SafeBrowsingUnavailable(Exception):
    """Safe Browsing 검사를 수행하지 못함(키 미설정/네트워크/non-200/파싱). 호출부는 fail-closed.

    config_error=True 면 '키가 아예 없다'(운영자 설정 문제) — 사용자 메시지를 다르게 낸다.
    """

    def __init__(self, detail: str, *, config_error: bool = False):
        super().__init__(detail)
        self.detail = detail
        self.config_error = config_error


_CONTROL_RE = re.compile(r"[\x00-\x20\x7f-\x9f]")  # ASCII 제어문자·공백 + C1


# --------------------------------------------------------------------------- #
# 스테이지 2 정책 블랙리스트 — bot/url_blacklist.json (없거나 깨지면 _DEFAULT_BLACKLIST 폴백)
# --------------------------------------------------------------------------- #
_BLACKLIST_PATH = Path(__file__).resolve().parent / "url_blacklist.json"

# url_blacklist.json 이 없거나 깨졌을 때 쓰는 내장 기본값. 배포 시 같은 내용의 url_blacklist.json 도 함께 둔다 — 그게 진실의 원천.
_DEFAULT_BLACKLIST: list[dict] = [
    {
        "name": "blocked_platform",
        "message": "유튜브·SNS 같은 데는 게시판이 아니라서 등록할 수 없어요.",
        "host_suffix": ["youtube.com", "youtu.be", "x.com", "twitter.com",
                        "instagram.com", "facebook.com", "fb.com", "fb.watch",
                        "tiktok.com", "threads.net", "linkedin.com", "lnkd.in", "pinterest.com"],
        "path_ext": [],
    },
    {
        "name": "blocked_shortener",
        "message": "축약 링크(bit.ly 등)는 등록할 수 없어요 — 펼친 원래 URL 을 주세요.",
        "host_suffix": ["bit.ly", "bit.do", "bitly.com", "tinyurl.com", "t.co", "goo.gl",
                        "ow.ly", "is.gd", "buff.ly", "rebrand.ly", "cutt.ly", "shorturl.at",
                        "han.gl", "me2.do", "url.kr", "vo.la", "abr.ge"],
        "path_ext": [],
    },
    {
        "name": "binary_file",
        "message": "파일 직링(.pdf·.zip 등)은 받을 수 없어요 — 게시판 목록 페이지 URL 을 주세요.",
        "host_suffix": [],
        "path_ext": [".pdf", ".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2",
                     ".exe", ".dmg", ".msi", ".apk", ".iso", ".bin",
                     ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm",
                     ".mp3", ".wav", ".flac", ".m4a", ".ogg",
                     ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".ico", ".tiff", ".heic",
                     ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".hwp", ".hwpx"],
    },
]

# (mtime, 정규화된 그룹들, 상태문자열) — mtime 바뀌면 재로드. 이벤트 루프 스레드에서만 접근(락 불필요).
_blacklist_cache: Optional[tuple[float, list[dict], str]] = None
_blacklist_last_error: Optional[str] = None  # 같은 에러를 매 검사마다 다시 로깅하지 않으려고


def _normalize_groups(raw: object, source: str) -> list[dict]:
    """raw('groups' 리스트)를 검증·정규화 → [{name, message, host_suffix:tuple, path_ext:tuple}, ...]. 잘못되면 ValueError."""
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{source}: 'groups' 가 비어있지 않은 리스트여야 함")
    out: list[dict] = []
    for i, g in enumerate(raw):
        if not isinstance(g, dict):
            raise ValueError(f"{source}: groups[{i}] 가 객체가 아님")
        name, message = g.get("name"), g.get("message")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{source}: groups[{i}].name 누락/빈 문자열")
        if not isinstance(message, str) or not message.strip():
            raise ValueError(f"{source}: groups[{i}].message 누락/빈 문자열")
        host_suffix, path_ext = g.get("host_suffix") or [], g.get("path_ext") or []
        if not isinstance(host_suffix, list) or not isinstance(path_ext, list):
            raise ValueError(f"{source}: groups[{i}].host_suffix/path_ext 는 리스트여야 함")
        for fld, items in (("host_suffix", host_suffix), ("path_ext", path_ext)):
            for j, s in enumerate(items):
                if not isinstance(s, str):
                    raise ValueError(f"{source}: groups[{i}].{fld}[{j}] 가 문자열이 아님 ({type(s).__name__})")
        hs = tuple(s.strip().lower().lstrip(".") for s in host_suffix if s.strip())
        pe = tuple("." + s.strip().lower().lstrip(".") for s in path_ext if s.strip())
        if not hs and not pe:
            raise ValueError(f"{source}: groups[{i}]({name}) 에 host_suffix 도 path_ext 도 없음")
        out.append({"name": name.strip(), "message": message.strip(), "host_suffix": hs, "path_ext": pe})
    return out


_DEFAULT_BLACKLIST_NORM = _normalize_groups(_DEFAULT_BLACKLIST, "_DEFAULT_BLACKLIST")  # 모듈 import 시 한 번 — 여기서 깨지면 코드 버그


def _load_blacklist() -> tuple[list[dict], str]:
    """(정규화된 그룹 리스트, 상태문자열). 파일 없음/JSON·스키마 깨짐 → 내장 기본값."""
    global _blacklist_cache, _blacklist_last_error
    try:
        mtime = _BLACKLIST_PATH.stat().st_mtime
    except OSError:
        return _DEFAULT_BLACKLIST_NORM, "내장 기본값 (url_blacklist.json 없음)"
    if _blacklist_cache is not None and _blacklist_cache[0] == mtime:
        return _blacklist_cache[1], _blacklist_cache[2]
    try:
        data = json.loads(_BLACKLIST_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "groups" not in data:
            raise ValueError('최상위가 {"groups": [...]} 객체여야 함')
        groups = _normalize_groups(data["groups"], "url_blacklist.json")
        status = f"url_blacklist.json ({len(groups)} groups)"
        _blacklist_last_error = None
    except Exception as e:  # noqa: BLE001
        emsg = f"{type(e).__name__}: {e}"
        if emsg != _blacklist_last_error:
            log.warning("url_blacklist.json 로드/검증 실패 — 내장 기본값 사용: %s", emsg)
            _blacklist_last_error = emsg
        groups = _DEFAULT_BLACKLIST_NORM
        status = f"⚠ url_blacklist.json 로드 실패({type(e).__name__}) — 내장 기본값"
    _blacklist_cache = (mtime, groups, status)
    return groups, status


def blacklist_status() -> str:
    """현재 블랙리스트 출처 ('url_blacklist.json (3 groups)' / '내장 기본값 ...' / '⚠ ... 로드 실패 ...')."""
    return _load_blacklist()[1]


# --------------------------------------------------------------------------- #
# 24h 거부 카운터 (in-process)
# --------------------------------------------------------------------------- #
_REJ_WINDOW = 86400.0
_REJECTIONS: "deque[tuple[float, str]]" = deque()


def _trim(now: float) -> None:
    cutoff = now - _REJ_WINDOW
    while _REJECTIONS and _REJECTIONS[0][0] < cutoff:
        _REJECTIONS.popleft()


def _record(reason: str) -> None:
    now = time.time()
    _REJECTIONS.append((now, reason))
    _trim(now)


def rejection_summary_24h() -> dict[str, int]:
    """최근 24h 거부 건수를 reason 별로. 봇 재시작 시 리셋(in-process)."""
    _trim(time.time())
    out: dict[str, int] = {}
    for _, reason in _REJECTIONS:
        out[reason] = out.get(reason, 0) + 1
    return out


def _reject(reason: str, msg: str) -> NoReturn:
    _record(reason)
    raise UrlRejected(reason, msg)


# --------------------------------------------------------------------------- #
# 스테이지 1: 구조 검증
# --------------------------------------------------------------------------- #
def _lbl(label: str) -> str:
    return "" if label == "url" else "참고 글 URL(article_url): "


def _check_structural(u: str, label: str) -> str:
    """통과하면 소문자 hostname 반환. 실패하면 _reject."""
    if not isinstance(u, str) or not u.strip():
        _reject("malformed", f"{_lbl(label)}URL 이 비어 있어요.")
    if _CONTROL_RE.search(u):
        _reject("malformed", f"{_lbl(label)}URL 에 공백/제어문자가 들어 있어요.")
    try:
        p = urlsplit(u)
    except ValueError as e:
        _reject("malformed", f"{_lbl(label)}URL 형식이 잘못됐어요 ({e}).")
    if p.scheme.lower() not in ("http", "https"):
        _reject("bad_scheme", f"{_lbl(label)}http(s):// 로 시작하는 URL 만 됩니다.")
    if p.username or p.password:
        _reject("has_userinfo", f"{_lbl(label)}URL 에 user:password@ 같은 인증 정보를 넣지 마세요.")
    host = (p.hostname or "").strip()
    if not host:
        _reject("malformed", f"{_lbl(label)}URL 에 호스트(도메인)가 없어요.")
    # host 가 IP 리터럴(공인·사설·IPv6)이면 거부 — 게시판이 맨 IP 에 올라간 경우는 없음.
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass  # IP 가 아님 = 도메인 이름 → OK
    else:
        _reject("ip_literal_host", f"{_lbl(label)}도메인 이름으로 주세요 — IP 주소({host})는 등록할 수 없어요.")
    return host.lower()


# --------------------------------------------------------------------------- #
# 스테이지 2: 정책 블랙리스트 — _load_blacklist() 의 그룹들을 위에서부터, 첫 매치로 거부
# --------------------------------------------------------------------------- #
def _host_matches(host: str, suffixes: tuple[str, ...]) -> bool:
    return any(host == s or host.endswith("." + s) for s in suffixes)


def _check_policy(u: str, label: str) -> None:
    p = urlsplit(u)
    host = (p.hostname or "").lower().rstrip(".")  # 끝의 FQDN 점 제거
    path = (p.path or "").lower()
    for g in _load_blacklist()[0]:
        if g["host_suffix"] and _host_matches(host, g["host_suffix"]):
            _reject(g["name"], f"{_lbl(label)}{g['message']}")
        if g["path_ext"] and path.endswith(g["path_ext"]):
            _reject(g["name"], f"{_lbl(label)}{g['message']}")


# --------------------------------------------------------------------------- #
# 스테이지 3: SSRF (DNS)
# --------------------------------------------------------------------------- #
async def _resolve(host: str) -> list[str]:
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError:
        # 비ASCII 호스트인데 IDNA 인코딩이 실패하면 진짜 malformed. ASCII 호스트는 idna 코덱이 까다로워
        # 막혀도(언더스코어 등) getaddrinfo 가 처리하기도 하므로 원본으로 통과시킨다.
        if not host.isascii():
            _reject("malformed", f"호스트 이름({host}) 이 올바르지 않아요.")
        ascii_host = host
    loop = asyncio.get_running_loop()
    infos: list = []
    try:
        infos = await asyncio.wait_for(
            loop.getaddrinfo(ascii_host, None, type=socket.SOCK_STREAM), timeout=5.0
        )
    except asyncio.TimeoutError:
        _reject("dns_failed", f"이 도메인({host}) 이름 해석이 너무 오래 걸려요 — 잠시 후 다시 시도해 주세요.")
    except socket.gaierror:
        _reject("dns_failed", f"이 도메인({host}) 을 찾을 수 없어요 (DNS 실패).")
    except UnicodeError:
        _reject("malformed", f"호스트 이름({host}) 이 올바르지 않아요.")
    ips: list[str] = []
    for _fam, _stype, _proto, _canon, sockaddr in infos:
        ip = sockaddr[0]
        if ip not in ips:
            ips.append(ip)
    if not ips:
        _reject("dns_failed", f"이 도메인({host}) 의 IP 를 얻지 못했어요.")
    return ips


def _check_ip(ip_str: str, host: str, label: str) -> None:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return  # IP 가 아니면(거의 안 일어남) 그냥 통과
    if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
            or ip.is_multicast or ip.is_unspecified):
        _reject("ssrf_blocked",
                f"{_lbl(label)}이 도메인({host}) 이 내부망/로컬 주소({ip}) 로 연결돼요 — 등록할 수 없어요.")


# --------------------------------------------------------------------------- #
# 스테이지 4: Safe Browsing (Google Safe Browsing v4 threatMatches:find)
# --------------------------------------------------------------------------- #
# v5 urls:search 는 JSON 출력을 지원하지 않고 protobuf 만 반환한다("Unsupported Output Format") — 그래서 v4 사용.
# v4 는 2027-03-31 종료 예정이지만 그땐 이 함수만 v5(protobuf 디코딩) 또는 Web Risk 로 교체하면 된다.
_GSB_ENDPOINT = "https://safebrowsing.googleapis.com/v4/threatMatches:find"
_GSB_THREAT_TYPES = ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION"]
_GSB_CLIENT_ID = "notice-watcher"
_GSB_CLIENT_VERSION = "1.0"


async def is_url_safe(urls: list[str]) -> dict[str, list[str]]:
    """플래그된 URL → threatType 목록. 빈 dict = 전부 안전.

    실패(키 미설정/네트워크/non-200/JSON 파싱)는 SafeBrowsingUnavailable 로 — 호출부는 fail-closed.
    추상화 경계: 여기만 v5/Web Risk 로 갈아끼우면 제공자 교체 끝.
    """
    key = safe_browsing_api_key()
    if not key:
        raise SafeBrowsingUnavailable("SAFE_BROWSING_API_KEY 미설정", config_error=True)
    if not urls:
        return {}
    body = {
        "client": {"clientId": _GSB_CLIENT_ID, "clientVersion": _GSB_CLIENT_VERSION},
        "threatInfo": {
            "threatTypes": _GSB_THREAT_TYPES,
            "platformTypes": ["ANY_PLATFORM"],
            "threatEntryTypes": ["URL"],
            "threatEntries": [{"url": u} for u in urls[:500]],
        },
    }
    try:
        async with httpx.AsyncClient(timeout=4.0, follow_redirects=False) as client:
            r = await client.post(_GSB_ENDPOINT, params={"key": key}, json=body)
    except Exception as e:  # noqa: BLE001  네트워크/타임아웃 등 무엇이든
        raise SafeBrowsingUnavailable(f"요청 실패: {type(e).__name__}: {e}") from e
    if r.status_code != 200:
        raise SafeBrowsingUnavailable(f"HTTP {r.status_code}: {r.text[:200]}")
    try:
        data = r.json()
    except Exception as e:  # noqa: BLE001
        raise SafeBrowsingUnavailable("응답 JSON 파싱 실패") from e
    out: dict[str, list[str]] = {}
    for m in (data.get("matches") or []):
        u = (m.get("threat") or {}).get("url") or "?"
        tt = m.get("threatType")
        out.setdefault(u, [])
        if tt and tt not in out[u]:
            out[u].append(tt)
    return out


async def _check_safe_browsing(urls: list[str]) -> None:
    threats: dict[str, list[str]] = {}
    try:
        threats = await is_url_safe(urls)
    except SafeBrowsingUnavailable as e:
        if e.config_error:
            _reject("gsb_error",
                    "Safe Browsing 검사 설정이 안 돼 있어요 — 운영자에게 문의해 주세요 (.env 의 SAFE_BROWSING_API_KEY).")
        _reject("gsb_error", "Safe Browsing 검사를 못 했어요 — 잠시 후 다시 시도해 주세요.")
    if threats:
        # GSB match 에 threatType 이 빠져 있으면(드묾) threats 값이 빈 리스트라 set 이 빌 수 있음 → "UNKNOWN" 으로.
        types = sorted({tt for v in threats.values() for tt in v}) or ["UNKNOWN"]
        _reject("malicious",
                f"이 URL 은 악성으로 신고된 적이 있어요 (Google Safe Browsing: {', '.join(types)}) — 등록하지 않습니다.")


# --------------------------------------------------------------------------- #
# 오케스트레이션
# --------------------------------------------------------------------------- #
async def check(url: str, *, article_url: Optional[str] = None,
                skip_dns: bool = False, skip_gsb: bool = False,
                progress: Optional[Callable[[str], None]] = None) -> None:
    """url(과 주어졌으면 article_url)을 게이트에 통과시킨다. 통과하면 None, 막히면 UrlRejected.

    progress 콜백이 주어지면 각 스테이지 통과 시 사람이 읽을 한 줄을 넘긴다(CLI 용; 봇은 안 씀).
    """
    targets: list[tuple[str, str]] = [("url", url)]
    if article_url:
        targets.append(("article_url", article_url))

    # 1) 구조 검증
    hosts: list[tuple[str, str]] = []  # (label, host) — 중복 호스트 제거하면서
    for label, u in targets:
        h = _check_structural(u, label)
        if h not in (x[1] for x in hosts):
            hosts.append((label, h))
    if progress:
        progress(f"1) 구조 검증 OK ({len(targets)}개 URL)")

    # 2) 정책 블랙리스트
    for label, u in targets:
        _check_policy(u, label)
    if progress:
        progress(f"2) 정책 블랙리스트 OK — {blacklist_status()}")

    # 3) SSRF (DNS) — 호스트 단위로 1회씩
    if skip_dns:
        if progress:
            progress("3) SSRF(DNS) 검사 스킵 (--no-dns)")
    else:
        for label, h in hosts:
            ips = await _resolve(h)
            for ip in ips:
                _check_ip(ip, h, label)
            if progress:
                progress(f"3) DNS {h} → {', '.join(ips)} (사설/loopback 아님)")

    # 4) Safe Browsing
    if skip_gsb:
        if progress:
            progress("4) Safe Browsing 검사 스킵 (--no-gsb)")
        return
    await _check_safe_browsing([u for _, u in targets])
    if progress:
        progress("4) Safe Browsing OK (위협 없음)")


# --------------------------------------------------------------------------- #
# 단독 실행 CLI
# --------------------------------------------------------------------------- #
def _main(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m bot.url_gate",
        description="probe 전단 URL 게이트 — URL 하나(또는 +article_url)를 검사하고 통과/거부를 출력.",
    )
    ap.add_argument("url", help="검사할 게시판 목록 URL")
    ap.add_argument("--article-url", default=None, help="(선택) 함께 검사할 글 본문 URL")
    ap.add_argument("--no-gsb", action="store_true", help="Safe Browsing(4단계) 스킵 — 키 없이 구조/SSRF/블랙리스트만")
    ap.add_argument("--no-dns", action="store_true", help="SSRF(DNS 해석, 3단계) 스킵")
    args = ap.parse_args(argv)

    print(f"[url_gate] 검사: {args.url}"
          + (f"  (+article_url: {args.article_url})" if args.article_url else ""))

    def _progress(s: str) -> None:
        print(f"  ✓ {s}")

    try:
        asyncio.run(check(args.url, article_url=args.article_url,
                          skip_dns=args.no_dns, skip_gsb=args.no_gsb, progress=_progress))
    except UrlRejected as e:
        print(f"\n✗ 거부 — reason={e.reason}\n  {e.msg}")
        return 1
    except KeyboardInterrupt:
        print("\n(중단됨)")
        return 130
    print("\n✓ 통과 — 이 URL 은 probe 단계로 진행됩니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
