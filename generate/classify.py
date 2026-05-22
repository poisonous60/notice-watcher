"""LLM page-type 분류기 — register 게이트의 false-reject veto + soft 신호 arbiter.

출력 클래스: index(게시판) / content(단일 글) / not_found(not-found shell) / login(로그인 게이트).
게이트(`_board_shape_check` 등)가 거부하려 할 때 호출. 결과 'index' 면 거부 취소.
not_found/login 은 퍼지 본문-휴리스틱(옛 soft-404 regex / login 본문-마커)을 대체하는 arbiter (ADR 0007 §확장 2026-05-22).
근거: arXiv 2505.06972 (LLM index/content 분류 F1 0.89 / precision 0.98) +
PoC 실측 (board recall 0.905, article precision 1.000, gemini-2.5-flash).
설계: `docs/plans/llm-index-content-classifier.md`.

입력 HTML 은 **raw 파일**(`digest["list_html"]["source"]`) 우선 — cleaned `["html"]` 은
200KB cap + script/meta strip 으로 SPA 본문이 잘려 분류가 무너짐(실측). source 없으면 cleaned,
둘 다 없으면 class='?'.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from .prompts import render_prompt
from .routing import client_for
from .llm_base import LLMClient, LLMError

_SYSTEM = render_prompt("classify.system")
_BODY_CAP = 2000
_RETRY = 3


def _read_list_html(digest: dict) -> str:
    """raw 파일(source) 우선, cleaned html fallback. 둘 다 없으면 ''."""
    lh = digest.get("list_html") or {}
    src = lh.get("source")
    if src:
        try:
            return Path(src).read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
    return lh.get("html") or ""


def _extract_title_body(html: str, url: str) -> tuple[str, str]:
    """trafilatura 로 title+body. favor_recall (PoC 검증). 실패/미설치 시 ('','')."""
    if not html:
        return "", ""
    try:
        import trafilatura
    except ImportError:
        return "", ""
    try:
        doc = trafilatura.bare_extraction(html, url=url or None,
                                          favor_recall=True, with_metadata=True)
    except Exception:  # noqa: BLE001 — 추출 실패가 분류를 막으면 안 됨
        return "", ""
    if not doc:
        return "", ""
    if isinstance(doc, dict):
        return (doc.get("title") or "", doc.get("text") or "")
    return (getattr(doc, "title", "") or "", getattr(doc, "text", "") or "")


def _struct_hint(digest: dict, url: str) -> str:
    """list_candidates 의 같은-호스트 반복 글-행 / 피드 신호 압축. 게시판 판정 보조."""
    lc = digest.get("list_candidates") or {}
    host = (urlsplit(url).hostname or "").lower()
    rows: list[tuple[int, str]] = []
    for p in (lc.get("html_repeating_patterns") or []):
        hp = p.get("href_pattern_guess") or p.get("sample_url") or ""
        if not hp:
            continue
        # 상대경로(`/t/{n}`)는 같은-호스트로 간주. 절대 URL 은 hostname 정확 비교
        # (substring 매칭은 example.com 이 notexample.com 에 오매칭 + 포트 오작동).
        h = (urlsplit(hp).hostname or "").lower()
        if (not h and hp.startswith("/")) or (host and h == host):
            rows.append((p.get("child_count", 0), hp))
    rows.sort(reverse=True)
    feed = len(digest.get("feed_candidates") or [])
    parts: list[str] = []
    if rows:
        parts.append(f"같은-호스트 반복 글-링크 행 {len(rows)}종 (최다 {rows[0][0]}행, 예: {rows[0][1][:60]})")
    else:
        parts.append("정적 HTML 에 같은-호스트 반복 글-행 패턴 없음 (SPA 렌더일 수 있음)")
    if feed:
        parts.append(f"RSS/Atom 피드 {feed}건")
    return "; ".join(parts)


_PAGE_TYPES = ("index", "content", "catalog", "not_found", "login")


def _parse(text: str) -> dict:
    try:
        d = json.loads(text)
        cls = d.get("class")
        if cls in _PAGE_TYPES:
            return {"class": cls,
                    "confidence": float(d.get("confidence", 0.0) or 0.0),
                    "reason": str(d.get("reason", ""))[:200]}
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return {"class": "?", "confidence": 0.0, "reason": f"parse_fail: {text[:80]}"}


def classify_index_content(*, url: str, digest: dict,
                           client: Optional[LLMClient] = None,
                           slug: Optional[str] = None) -> dict:
    """페이지 타입 분류 — index(게시판) / content(단일 글) / not_found(없음 shell) / login(로그인 게이트).

    반환: {"class": "index"|"content"|"not_found"|"login"|"?", "confidence": float, "reason": str}.
    LLM 실패/parse 실패/HTML 부재 → class='?' (caller 가 status-quo 유지 = fail-safe).
    not_found→url_dead(rc4), login→policy_reject(rc2), content→gate_reject(rc3) 매핑은 register 가 함 (ADR 0007 §확장).
    """
    html = _read_list_html(digest)
    title, body = _extract_title_body(html, url)
    if not html and not title and not body:
        return {"class": "?", "confidence": 0.0, "reason": "list_html 없음 — 분류 불가"}

    user = render_prompt(
        "classify.user_skeleton",
        url=url or "(없음)",
        title=title or "(없음)",
        struct=_struct_hint(digest, url),
        body=(body or "").strip()[:_BODY_CAP] or "(본문 없음)",
    )
    cli = client if client is not None else client_for("classify_index_content")

    last: Optional[Exception] = None
    for attempt in range(1, _RETRY + 1):
        try:
            resp = cli.generate(system_instruction=_SYSTEM, user_text=user,
                                temperature=0.0, json_mode=True,
                                call_site="classify_index_content", slug=slug,
                                attempt=attempt)
            return _parse(resp.text)
        except LLMError as e:
            last = e
            if attempt < _RETRY:
                time.sleep(2 * attempt)
    return {"class": "?", "confidence": 0.0, "reason": f"llm_fail: {last}"}


__all__ = ["classify_index_content"]
