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

from contextlib import contextmanager
import json
import time
from pathlib import Path
from typing import Any, Iterator, Optional
from urllib.parse import parse_qsl, urlsplit

from engine.tracing import current_trace

from .prompts import render_prompt
from .routing import client_for
from .llm_base import LLMClient, LLMError

_SYSTEM = render_prompt("classify.system")
_BODY_CAP = 2000
_RETRY = 3
_MIN_WALL_REMAINING_S = 5.0
_MAX_ATTEMPT_TIMEOUT_S = 60.0
_DETAIL_PATH_SEGMENTS = {"view", "detail", "article", "post"}
_ARTICLE_ID_PARAMS = {
    "articleid",
    "article_id",
    "article",
    "postid",
    "post_id",
    "seq",
    "no",
    "id",
    "idx",
    "wr_id",
}
_BOARD_ID_PARAMS = {"bbsid", "bbs_id", "boardid", "board_id", "menuid", "menucd", "mid"}


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


def _has_detail_path_segment(path: str) -> bool:
    for seg in (s.lower() for s in path.split("/") if s):
        stem = seg.rsplit(".", 1)[0]
        if stem in _DETAIL_PATH_SEGMENTS:
            return True
    return False


def _is_article_id_param(name: str) -> bool:
    n = name.lower().replace("-", "_")
    compact = n.replace("_", "")
    if compact in _BOARD_ID_PARAMS:
        return False
    return compact in _ARTICLE_ID_PARAMS or compact.endswith("articleid")


def _view_link_signature(href: str) -> Optional[str]:
    """Detail-page URL shape whose article identity lives in the query string."""
    u = urlsplit(href)
    if not u.query or not _has_detail_path_segment(u.path):
        return None
    id_params = [name for name, _ in parse_qsl(u.query, keep_blank_values=True)
                 if _is_article_id_param(name)]
    if not id_params:
        return None
    params = ",".join(dict.fromkeys(id_params[:3]))
    return f"{u.path}?{params}=<id-like>"


def _struct_hint(digest: dict, url: str) -> str:
    """list_candidates 의 같은-호스트 반복 cluster (글-링크/nav 모두) + 피드 신호 압축.

    옛 hint 는 *글-링크 행만* 박고 갯수+최다 child_count 만 출력했다 → espn.com/soccer 류
    이질 카드 hub (nav/team-list cluster 多 + article cluster 0) 신호가 다 가려져 분류기가
    'SPA index' 로 false-accept (2026-05-25 sports batch).

    개선: 같은-호스트 반복 cluster *전부* 의 path prefix 다양도 + 대표 sample 을 그대로 박고
    글-링크/nav 판별은 분류기 LLM 에 맡긴다 (휴리스틱 false-reject 회피).
    """
    lc = digest.get("list_candidates") or {}
    host = (urlsplit(url).hostname or "").lower()
    clusters: list[tuple[int, str, str, Optional[str]]] = []  # (cc, path_or_url, path_prefix, view_sig)
    for p in (lc.get("html_repeating_patterns") or []):
        hp = p.get("href_pattern_guess") or p.get("sample_url") or ""
        if not hp:
            continue
        h = (urlsplit(hp).hostname or "").lower()
        same_host = (not h and hp.startswith("/")) or (host and h == host)
        if not same_host:
            continue
        cc = int(p.get("child_count", 0) or 0)
        if cc < 3:
            continue
        path = urlsplit(hp).path or hp
        segs = [s for s in path.split("/") if s and not s.startswith("{")]
        prefix = "/" + (segs[0] if segs else "")
        clusters.append((cc, path or hp, prefix, _view_link_signature(hp)))
    clusters.sort(reverse=True)
    parts: list[str] = []
    if clusters:
        prefixes = sorted({p for _, _, p, _ in clusters})
        view_links = [(cc, sig) for cc, _, _, sig in clusters if sig]
        samples = "; ".join(
            f"cc={cc} {(sig or p)[:50]}{' (view-link cluster)' if sig else ''}"
            for cc, p, _, sig in clusters[:5]
        )
        parts.append(
            f"같은-호스트 반복 cluster {len(clusters)}종 "
            f"(path prefix {len(prefixes)}종: {', '.join(prefixes[:6])}; "
            f"top: {samples})"
        )
        if view_links:
            view_samples = "; ".join(f"cc={cc} {sig}" for cc, sig in view_links[:3])
            parts.append(
                f"view-link cluster {len(view_links)}종 = article cluster "
                f"(path detail segment + query id-like param; top: {view_samples})"
            )
        # 이질 카드 hub 강조 신호: path prefix ≥ 4 (서로 다른 섹션 루트 多 = 글-링크가 아닌 nav/카테고리)
        # → 분류기에 명시 red-flag (struct hint 가 body 보다 약해 false-accept 나는 케이스 봉합).
        if len(prefixes) >= 4 and not view_links:
            parts.append(
                f"⚠ 이질 카드 hub 신호: path prefix {len(prefixes)}종 ≥ 4 "
                "(섹션별 카테고리 hub — 사람이 봤을 때 '카드 종류를 한 줄로 못 묶음'). "
                "글-링크 cluster (같은 prefix + 다른 slug/ID) 가 흔적 없으면 class=content 가능성 큼."
            )
    else:
        parts.append("정적 HTML 에 같은-호스트 반복 cluster 없음 (SPA 렌더 또는 nav 만)")
    feed = len(digest.get("feed_candidates") or [])
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


def _remaining_wall_budget(wall_deadline: Optional[float]) -> Optional[float]:
    if wall_deadline is None:
        return None
    return max(0.0, wall_deadline - time.monotonic())


def _wall_deadline_result(rem: float) -> dict:
    return {"class": "?", "confidence": 0.0, "reason": f"wall_deadline_exhausted: rem={rem:.1f}s"}


def _client_timeout_targets(client: LLMClient) -> list[tuple[Any, float]]:
    out: list[tuple[Any, float]] = []
    seen: set[int] = set()

    def visit(obj: Any) -> None:
        oid = id(obj)
        if oid in seen:
            return
        seen.add(oid)
        if hasattr(obj, "timeout"):
            try:
                out.append((obj, float(getattr(obj, "timeout"))))
            except (TypeError, ValueError):
                pass
        for child_name in ("primary", "fallback"):
            child = getattr(obj, child_name, None)
            if child is not None:
                visit(child)

    visit(client)
    return out


@contextmanager
def _temporary_client_timeout(client: LLMClient, timeout_s: Optional[float]) -> Iterator[None]:
    if timeout_s is None:
        yield
        return
    targets = _client_timeout_targets(client)
    try:
        for obj, _old in targets:
            setattr(obj, "timeout", timeout_s)
        yield
    finally:
        for obj, old in targets:
            setattr(obj, "timeout", old)


def classify_index_content(*, url: str, digest: dict,
                           client: Optional[LLMClient] = None,
                           slug: Optional[str] = None,
                           wall_deadline: Optional[float] = None) -> dict:
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

    tr = current_trace()
    last: Optional[Exception] = None
    with tr.span("classify_index_content", attrs={"slug": slug, "retries": _RETRY}):
        for attempt in range(1, _RETRY + 1):
            rem = _remaining_wall_budget(wall_deadline)
            if rem is not None and rem < _MIN_WALL_REMAINING_S:
                return _wall_deadline_result(rem)
            timeout_s = min(rem, _MAX_ATTEMPT_TIMEOUT_S) if rem is not None else None
            try:
                with tr.span("classify_call", attrs={"attempt": attempt,
                                                     "call_site": "classify_index_content",
                                                     "timeout_s": timeout_s}):
                    with _temporary_client_timeout(cli, timeout_s):
                        resp = cli.generate(system_instruction=_SYSTEM, user_text=user,
                                            temperature=0.0, json_mode=True,
                                            call_site="classify_index_content", slug=slug,
                                            attempt=attempt)
                return _parse(resp.text)
            except LLMError as e:
                last = e
                if attempt < _RETRY:
                    rem = _remaining_wall_budget(wall_deadline)
                    if rem is not None and rem < _MIN_WALL_REMAINING_S:
                        return _wall_deadline_result(rem)
                    delay_s = 2 * attempt
                    if rem is not None:
                        delay_s = min(delay_s, max(0.0, rem - _MIN_WALL_REMAINING_S))
                    if delay_s > 0:
                        time.sleep(delay_s)
        return {"class": "?", "confidence": 0.0, "reason": f"llm_fail: {last}"}


__all__ = ["classify_index_content"]
