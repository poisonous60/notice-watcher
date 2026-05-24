"""Click-picker builder — 자동등록 실패 사이트용. dashboard 안 `/builder/*`.

흐름:
  GET  /builder                     URL 입력 폼
  POST /builder/start               URL → sid (in-memory)
  GET  /builder/edit/{sid}          iframe + 6-step UI
  GET  /builder/p/{sid}/{path}      sanitized + our-script-injected HTML
  POST /builder/api/save            payload → host_*.json + smoke fetch_list

보안 (codex review v2 FAIL 1 대응):
  - URL scheme allowlist (http/https)
  - DNS resolve → private/loopback/link-local IP 차단 (SSRF)
  - redirect 매 hop 동일 가드
  - <script>, on*=, javascript:/data:text/html URL, form action 모두 제거
  - 우리 picker.js/finder.min.js 만 inject — script-src 'self' CSP

한계 (명시):
  - 로그인 필요 사이트 X (cookie 보내지 X)
  - SPA — JS strip 으로 iframe 빈 화면 가능 (사용자에게 SPA 의심 경고)
  - cloudflare/captcha — target fetch 실패 시 그대로 에러 전달
"""
from __future__ import annotations

import ipaddress
import json
import secrets
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
CONFIGS_DIR = ROOT / "configs"
POLL_STATE_DIR = ROOT / "output" / "poll_state"

# codex fix #7: in-memory process-local. uvicorn workers>1 시 worker 사이 안 공유 →
# /builder/start 가 worker A 에 sid 만들고 /builder/edit 이 worker B 도달 시 404.
# scripts/dashboard.py 는 workers 명시 안 줘서 기본 1 → 현재 안 깨짐. workers>1 운영
# 시 SQLite/signed-cookie/session-affinity 로 교체 필요.
_SESSIONS: dict[str, dict] = {}
_SESSION_TTL = 60 * 60
_MAX_SESSIONS = 50


def _our_scripts(script_url: str) -> str:
    """완전 absolute URL — `<base href="target">` 가 relative path 를 target
    origin 으로 resolve 시켜 CSP 'self' (=target) 가 우리 script 차단하던 bug fix.
    호출자가 dashboard origin 기반 absolute URL 전달."""
    return f'<script type="module" src="{script_url}"></script>'


# --------------------------------------------------------------------------- #
# Pydantic models — codex fix #9. raw dict 받지 X. shape/size 한계 명시.
# --------------------------------------------------------------------------- #
_FIELD_NAMES = Literal["title", "link", "post_id", "date", "author", "category"]


class FieldSpec(BaseModel):
    selector: str = Field(..., min_length=1, max_length=500)
    attr: Optional[str] = Field(None, max_length=50)
    # 자동 매핑이 박는 transform — 예: [["regex_extract", "[?&]pkid=([^&#]+)"]]
    transforms: Optional[list[list]] = Field(None, max_length=8)


class SavePayload(BaseModel):
    sid: str = Field(..., min_length=1, max_length=64)
    row_selector: str = Field(..., min_length=1, max_length=500)
    include_notices: bool = True
    strategy: Literal["httpx_html", "playwright_html"] = "httpx_html"
    board: Optional[str] = Field(None, max_length=100)
    fields: dict[_FIELD_NAMES, FieldSpec] = Field(default_factory=dict)


def _is_blocked_ip(ip_str: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def _resolve_and_guard(host: str) -> None:
    """codex fix #3: any blocked → 전체 reject. DNS rebinding / alternate-address
    bypass 방어. 이전에는 1개라도 public 이면 통과시켜 httpx 가 재-resolve 시 다른
    blocked IP 로 connect 가능했음."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise HTTPException(400, f"DNS 실패: {host} ({e})")
    if not infos:
        raise HTTPException(400, f"DNS 결과 없음: {host}")
    public_seen = False
    for info in infos:
        ip = info[4][0]
        if _is_blocked_ip(ip):
            raise HTTPException(
                400, f"{host} resolved IP 中 blocked 포함 ({ip}) — SSRF 차단"
            )
        public_seen = True
    if not public_seen:
        raise HTTPException(400, f"{host} → public IP 없음 — 차단")


def _validate_target_url(url: str) -> str:
    if len(url) > 2048:
        raise HTTPException(400, "URL 너무 김")
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise HTTPException(400, f"scheme 허용 X: {p.scheme!r}")
    if not p.hostname:
        raise HTTPException(400, "host 빈값")
    _resolve_and_guard(p.hostname)
    return url


def _gc_sessions() -> None:
    now = time.time()
    for sid in list(_SESSIONS):
        if now - _SESSIONS[sid]["created_at"] > _SESSION_TTL:
            del _SESSIONS[sid]
    while len(_SESSIONS) > _MAX_SESSIONS:
        oldest = min(_SESSIONS, key=lambda k: _SESSIONS[k]["created_at"])
        del _SESSIONS[oldest]


def start_session(url: str) -> str:
    url = _validate_target_url(url)
    _gc_sessions()
    sid = secrets.token_urlsafe(12)
    p = urlparse(url)
    _SESSIONS[sid] = {
        "url": url,
        "scheme": p.scheme,
        "host": p.hostname,
        "created_at": time.time(),
    }
    return sid


def get_session(sid: str) -> Optional[dict]:
    sess = _SESSIONS.get(sid)
    if sess is None:
        return None
    if time.time() - sess["created_at"] > _SESSION_TTL:
        del _SESSIONS[sid]
        return None
    return sess


_BLOCKED_TAGS = {"script", "iframe", "object", "embed", "applet", "frame", "frameset"}


def _sanitize_html(html_text: str, base_href: str, script_url: str) -> str:
    soup = BeautifulSoup(html_text, "html.parser")

    # codex fix #4: <script>, <iframe srcdoc>, <object data>, <embed>, applet,
    # frame/frameset 모두 제거. SVG 안 <script> 도 동일 태그명 매칭으로 잡힘.
    for tag_name in _BLOCKED_TAGS:
        for s in soup.find_all(tag_name):
            s.decompose()

    # meta http-equiv=refresh 제거 — JS 없이 redirect 가능
    for m in soup.find_all("meta"):
        he = m.get("http-equiv") or ""
        if isinstance(he, str) and he.lower() == "refresh":
            m.decompose()

    for ln in soup.find_all("link"):
        rel = ln.get("rel") or []
        if isinstance(rel, list):
            rel_str = " ".join(rel).lower()
        else:
            rel_str = str(rel).lower()
        if "stylesheet" not in rel_str:
            ln.decompose()

    for tag in soup.find_all(True):
        for attr in list(tag.attrs.keys()):
            lk = attr.lower()
            if lk.startswith("on"):
                del tag.attrs[attr]
                continue
            if lk in ("href", "src", "action", "formaction", "srcdoc", "data", "background", "ping"):
                val = tag.attrs.get(attr)
                if isinstance(val, str):
                    v = val.lstrip().lower()
                    if v.startswith(("javascript:", "data:text/html", "vbscript:", "data:application/xhtml")):
                        del tag.attrs[attr]
                        continue
            if lk == "srcdoc":
                # iframe srcdoc 자체가 위험 — 위에서 iframe 제거하지만 다른 태그 srcdoc 잔존 방지
                del tag.attrs[attr]

    for f in soup.find_all("form"):
        f.attrs["onsubmit"] = "return false;"
        f.attrs["action"] = "javascript:void(0)"

    head = soup.find("head")
    if head is None:
        html_root = soup.find("html") or soup
        head = soup.new_tag("head")
        html_root.insert(0, head)
    for existing_base in head.find_all("base"):
        existing_base.decompose()
    head.insert(0, soup.new_tag("base", href=base_href))

    body = soup.find("body") or soup
    body.append(BeautifulSoup(_our_scripts(script_url), "html.parser"))

    return str(soup)


async def proxy_fetch(sid: str, path: str, script_url: str) -> HTMLResponse:
    sess = get_session(sid)
    if sess is None:
        raise HTTPException(404, "session 만료 또는 무효")
    target = urljoin(sess["url"], path) if path else sess["url"]
    target = _validate_target_url(target)

    async with httpx.AsyncClient(
        timeout=15.0,
        follow_redirects=False,
        headers={
            "User-Agent": "Mozilla/5.0 (notice-watcher picker)",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
        },
    ) as client:
        cur = target
        r: Optional[httpx.Response] = None
        for _ in range(6):
            r = await client.get(cur)
            if r.status_code in (301, 302, 303, 307, 308):
                loc = r.headers.get("location")
                if not loc:
                    break
                cur = urljoin(cur, loc)
                cur = _validate_target_url(cur)
                continue
            break
        else:
            raise HTTPException(400, "redirect loop")
    assert r is not None

    if r.status_code >= 400:
        raise HTTPException(r.status_code, f"target 응답 {r.status_code}")

    ct = r.headers.get("content-type", "").lower()
    if "html" not in ct and "xml" not in ct:
        raise HTTPException(400, f"HTML 아님 (content-type={ct})")

    sanitized = _sanitize_html(r.text, base_href=str(r.url), script_url=script_url)

    return HTMLResponse(
        sanitized,
        headers={
            "Content-Security-Policy": (
                "default-src 'self' data: blob:; "
                "img-src * data: blob:; "
                "style-src * 'unsafe-inline' data:; "  # target 외부 stylesheet 허용
                "font-src * data:; "
                "script-src 'self'; "  # target script 다 strip, 우리 것만
                "frame-src 'none'; "  # iframe 다 strip 했으니
                "connect-src 'none'; "  # XHR/fetch X
                "frame-ancestors 'self';"
            ),
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )


def _build_fields(fields_in: dict) -> dict:
    if "title" not in fields_in:
        raise HTTPException(400, "title field 필수")
    out: dict = {
        "title": [
            {
                "from": "css",
                "selector": fields_in["title"]["selector"],
                "text": True,
                "transform": [["collapse_ws"]],
            }
        ]
    }
    if "link" in fields_in:
        ld = fields_in["link"]
        out["url"] = [
            {
                "from": "css",
                "selector": ld["selector"],
                "attr": ld.get("attr") or "href",
            }
        ]
    if "post_id" in fields_in:
        pd = fields_in["post_id"]
        spec: dict = {"from": "css", "selector": pd["selector"]}
        if pd.get("attr"):
            spec["attr"] = pd["attr"]
        else:
            spec["text"] = True
        if pd.get("transforms"):
            spec["transform"] = pd["transforms"]
        out["post_id"] = [spec]
    if "date" in fields_in:
        dd = fields_in["date"]
        out["published_at"] = [
            {
                "from": "css",
                "selector": dd["selector"],
                "text": True,
                "transform": [["collapse_ws"], ["date_only_to_iso", "+09:00"]],
            }
        ]
    if "author" in fields_in:
        ad = fields_in["author"]
        out["author"] = [
            {
                "from": "css",
                "selector": ad["selector"],
                "text": True,
                "transform": [["collapse_ws"]],
            }
        ]
    if "category" in fields_in:
        cd = fields_in["category"]
        out["category"] = [
            {
                "from": "css",
                "selector": cd["selector"],
                "text": True,
                "transform": [["collapse_ws"]],
            }
        ]
    return out


def _config_from_picker(payload: dict, target_url: str) -> dict:
    p = urlparse(target_url)
    site = p.hostname or ""
    board = payload.get("board") or "notice"
    cfg = {
        "version": 1,
        "site": site,
        "board": str(board),
        "strategy": payload.get("strategy") or "httpx_html",
        "headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9",
        },
        "list": {
            "url_template": target_url,
            "pagination": {"kind": "none"},
            "row_selector": payload["row_selector"],
            "include_notices": bool(payload.get("include_notices", True)),
            "fields": _build_fields(payload.get("fields", {})),
        },
        "article": {
            "fetch_kind": "html",
            "content": [{"from": "css", "selector": "body", "html": True}],
        },
        "_source_url": target_url,
        "_note": "Generated via click-picker (dashboard /builder).",
    }
    return cfg


async def smoke_validate(cfg: dict) -> dict:
    """item ≥1 + title/post_id nonempty 검증 — codex FAIL 8 대응."""
    from engine.config_adapter import ConfigAdapter

    try:
        async with ConfigAdapter(cfg) as adapter:
            posts = await adapter.fetch_list(page_size=10)
    except Exception as e:
        return {"ok": False, "error": f"fetch_list 실패: {type(e).__name__}: {e}"}
    if not posts:
        return {"ok": False, "error": "item 0 — row_selector 가 매칭 안 됨"}
    n_title = sum(1 for p in posts if (getattr(p, "title", "") or "").strip())
    n_pid = sum(1 for p in posts if (getattr(p, "post_id", "") or "").strip())
    if n_title == 0:
        return {"ok": False, "error": "title 전부 빈값 — title selector 잘못", "n_posts": len(posts)}
    if n_pid == 0:
        return {"ok": False, "error": "post_id 전부 빈값 — post_id 매핑 확인", "n_posts": len(posts)}
    sample = [
        {
            "post_id": getattr(p, "post_id", None),
            "title": (getattr(p, "title", "") or "")[:60],
            "url": getattr(p, "url", None),
            "published_at": getattr(p, "published_at", None),
        }
        for p in posts[:3]
    ]
    post_ids = [
        (getattr(p, "post_id", "") or "").strip()
        for p in posts
        if (getattr(p, "post_id", "") or "").strip()
    ]
    return {"ok": True, "n_posts": len(posts), "sample": sample, "post_ids": post_ids}


def _write_baseline(slug: str, target_url: str, config_path: Path, post_ids: list[str]) -> str:
    """codex fix #8: save 직후 baseline 안 만들면 첫 polling 에 기존 N 항목 전부
    신규 알림 폭주. smoke 통과한 post_id 를 seen 으로 박음."""
    POLL_STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = POLL_STATE_DIR / f"{slug}.json"
    payload = {
        "slug": slug,
        "url": target_url,
        "config_path": str(config_path),
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "last_poll_at": None,
        "last_status": "registered",
        "consecutive_breakage": 0,
        "n_baseline": len(post_ids),
        "seen_post_ids": post_ids,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path.relative_to(ROOT))


async def save_config(payload: "SavePayload") -> dict:
    """codex fix #9: SavePayload Pydantic 으로 type/size 검증 후 받음."""
    sess = get_session(payload.sid)
    if sess is None:
        raise HTTPException(404, "session 만료")
    target_url = sess["url"]
    p_dict: dict[str, Any] = payload.model_dump()
    cfg = _config_from_picker(p_dict, target_url)

    smoke = await smoke_validate(cfg)
    if not smoke["ok"]:
        return {"ok": False, "stage": "smoke", **smoke, "config_preview": cfg}

    from engine.slug import url_to_slug

    slug = url_to_slug(target_url)
    out_path = CONFIGS_DIR / f"{slug}.json"
    if out_path.exists():
        return {
            "ok": False,
            "stage": "exists",
            "error": f"이미 등록됨: {out_path.name}",
            "config_preview": cfg,
        }
    out_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    baseline_path = _write_baseline(slug, target_url, out_path, smoke.get("post_ids", []))
    return {
        "ok": True,
        "config_path": str(out_path.relative_to(ROOT)),
        "baseline_path": baseline_path,
        "smoke": smoke,
    }
