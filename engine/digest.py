"""probe 산출물(output/probe/<slug>/) → gemini 입력용 digest(JSON).

핵심:
- 목록/글 HTML 을 *정제*해서 통째로 넣는다(script/style/svg/주석/인라인 핸들러/style/data: URI 제거,
  공백 collapse). >max_bytes 면 하드 truncate + 플래그. (M2: candidate 주변만 추출하는 정교한 fallback 은 TODO.)
- list_candidates.json 을 힌트로 그대로 첨부 (gemini 가 거의 베껴 쓰는 핵심 입력).
- SPA 면 __NEXT_DATA__/__NUXT__ 등 hydration 을 *별도로* 추출해 truncate 해서 첨부(정제 HTML 에선 큰 스크립트가 빠지므로).
- 통과 헤더(정적 OK 프리셋의 request 헤더 + headless captured 헤더), robots(crawl_delay/disallow), verdict/매트릭스.

사용:
    python -m engine.digest <slug> [--out digest.json] [--max-bytes 200000]
    python -m engine.digest --url "https://..."   # url → slug
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Comment, Tag

from engine._mdr_candidates import mdr_candidate_xpaths


# probe 패키지 import 를 위해 프로젝트 루트가 sys.path 에 있어야 함.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _mdr_candidates_safe(html: Optional[str]) -> list[dict]:
    """fail-soft wrapper: lxml/encoding 오류 다 빈 list 로 (measurement-only)."""
    if not html:
        return []
    try:
        return mdr_candidate_xpaths(html, top_k=10)
    except Exception:
        return []


_SITEMAP_ONLY_MIN_N = 30
_SITEMAP_POST_ID_RE = re.compile(r"(/\d{3,}/?$|/[\w-]+[-_]\d{3,}/?$|/\d{4}/\d{1,2}/[\w-]+/?$)")


def _sitemap_only_fit_signal(candidates: list) -> dict:
    """θ signal — canva/salesforce 처럼 *sitemap 만으로 polling 가능* 한 사이트 분류기 (signal-only).

    휴리스틱 (셋 다 만족):
      - candidates >= 30
      - 80% 이상이 stable post-id 같은 path suffix (`/123/`, `/slug-123/`, `/2026/05/title/` 등)
      - 동일한 depth-1 path segment 80% 이상 공유 (e.g. 다 `/blog/...`)

    Returns: {"sitemap_only_fit": bool, "n": int, "post_id_ratio": float, "top_prefix_ratio": float}.
    measurement-only — prompt 안 읽음. 손-adapter 자동화 candidate detection 용 signal.
    """
    out = {"sitemap_only_fit": False, "n": 0, "post_id_ratio": 0.0, "top_prefix_ratio": 0.0}
    if not candidates:
        return out
    n = len(candidates)
    out["n"] = n
    if n < _SITEMAP_ONLY_MIN_N:
        return out
    n_postid = 0
    prefixes: dict[str, int] = {}
    for c in candidates:
        u = c.get("url") if isinstance(c, dict) else None
        if not u:
            continue
        try:
            sp = urlsplit(u)
        except ValueError:
            continue
        path = sp.path or ""
        if _SITEMAP_POST_ID_RE.search(path):
            n_postid += 1
        parts = [s for s in path.split("/") if s]
        prefix = parts[0] if parts else ""
        prefixes[prefix] = prefixes.get(prefix, 0) + 1
    out["post_id_ratio"] = n_postid / n
    if prefixes:
        out["top_prefix_ratio"] = max(prefixes.values()) / n
    out["sitemap_only_fit"] = bool(out["post_id_ratio"] >= 0.8 and out["top_prefix_ratio"] >= 0.8)
    return out

from probe.paths import OUTPUT_ROOT, output_dir, url_to_slug  # noqa: E402

try:
    from probe.hydration import extract_hydration  # noqa: E402
except Exception:  # pragma: no cover
    extract_hydration = None  # type: ignore


DEFAULT_MAX_HTML_BYTES = 200_000
HYDRATION_MAX_BYTES = 50_000

# 정제 시 보존할 script 타입(보통 작고 데이터성). __NEXT_DATA__ 같이 큰 건 제거하고 hydration 으로 따로 첨부.
_KEEP_SCRIPT_TYPES = {"application/ld+json"}
_STRIP_TAGS = ["script", "style", "svg", "noscript", "template", "iframe", "canvas", "link", "meta"]


def clean_html(html: str, *, max_bytes: int = DEFAULT_MAX_HTML_BYTES) -> tuple[str, bool]:
    """정제된 HTML 과 truncated 여부."""
    if not html:
        return "", False
    soup = BeautifulSoup(html, "lxml")

    for tag in soup.find_all(_STRIP_TAGS):
        if tag.name == "script" and (tag.get("type") or "").lower() in _KEEP_SCRIPT_TYPES:
            continue
        tag.decompose()
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()

    for el in soup.find_all(True):
        attrs = getattr(el, "attrs", None)
        if not attrs:
            continue
        for k in list(attrs):
            kl = str(k).lower()
            if kl.startswith("on") or kl in ("style", "srcset"):
                del attrs[k]
                continue
            v = attrs[k]
            if isinstance(v, str) and v.strip().lower().startswith("data:"):
                del attrs[k]

    body = soup.body or soup
    out = str(body)
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n[ \t]+", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = out.strip()

    truncated = False
    if len(out.encode("utf-8")) > max_bytes:
        # 바이트 기준으로 자르되, 태그 중간에서 끊기지 않게 마지막 '>' 까지 되돌린다.
        # (candidate 주변만 추출하는 정교한 버전은 추후 — 지금은 LLM 입력이라 이 정도면 충분.)
        cut = out.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")
        last_gt = cut.rfind(">")
        if last_gt > max_bytes // 2:  # 너무 많이 잘리지 않는 선에서만
            cut = cut[: last_gt + 1]
        out = cut + "\n<!-- [digest] HTML truncated -->"
        truncated = True
    return out, truncated


# LLM 프롬프트 *입력 전용* 추가 압축 디폴트 (prompt.py 에서만 호출).
_KEEP_SIBLINGS = 3       # T1: 동일구조 형제 그룹당 남길 예시 수
_TEXT_NODE_CAP = 200     # T2: text 노드 최대 char (<a> 자손 제외)
_ATTR_VALUE_CAP = 80     # T3: data-*/aria-* 값 최대 char


def _sibling_signature(el: Tag) -> tuple:
    """T1 동일구조 형제 판정용. tag + class set + data-* 키 set + 직속 자식 tag 순서.

    class·data-* 키를 넣어야 핀/공지 row(보통 다른 class 또는 data-notice 류 키)가
    정상 row 와 안 합쳐진다(codex 리뷰 B1). 값이 아닌 *키* presence 만 — 값은 T3 가 자름.
    """
    classes = frozenset(el.get("class") or [])
    data_keys = frozenset(k for k in el.attrs if str(k).lower().startswith("data-"))
    child_tags = tuple(c.name for c in el.children if isinstance(c, Tag))
    return (el.name, classes, data_keys, child_tags)


def compress_html_for_prompt(
    html: str,
    *,
    keep_siblings: int = _KEEP_SIBLINGS,
    text_cap: int = _TEXT_NODE_CAP,
    attr_cap: int = _ATTR_VALUE_CAP,
) -> str:
    """clean_html 결과에 *추가* 압축 — selector 신호(tag/class/id/href/src/구조) 보존하면서 토큰 절감.

    prompt.py build_user_prompt 에서만 호출. digest["list_html"]["html"] 원본은 안 건드림 →
    validate(라이브 fetch)·retry enrich(list_candidates JSON)·probe_smoke 무영향(codex 리뷰 A/C).

    T1 반복형제 collapse: 부모별 동일 signature 형제 그룹 > keep_siblings 면 앞 keep_siblings 만
       남기고 나머지 제거 + `<!-- collapsed N similar <tag.class> -->` 주석.
    T2 긴 text 노드 cap: text_cap 초과 text 자름. `<a>` 자손 text 는 제외(글 제목·post_id 소스).
    T3 attr 값 cap: data-*/aria-* 값 attr_cap 초과 & 숫자-only 아니면 자름. class/id/href/src 불가침.
    """
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")

    # T1 — 부모별 동일구조 형제 collapse.
    # find_all 은 정적 리스트. 바깥 부모를 먼저 collapse 하면 그 안 형제들이 decompose 돼
    # 뒤에서 만나도 detached(name None / 자식 0) → skip. 안전하게 guard.
    for parent in soup.find_all(True):
        if parent.name is None:  # 이미 decompose 됨
            continue
        children = [c for c in parent.children if isinstance(c, Tag)]
        if len(children) <= keep_siblings:
            continue
        groups: dict[tuple, list[Tag]] = {}
        for c in children:
            groups.setdefault(_sibling_signature(c), []).append(c)
        for sig, els in groups.items():
            if len(els) <= keep_siblings:
                continue
            drop = els[keep_siblings:]  # 문서 순서 유지 (children 순회 순)
            cls = ".".join(sorted(sig[1])) if sig[1] else ""
            label = f"{sig[0]}{('.' + cls) if cls else ''}"
            drop[0].insert_before(Comment(f" collapsed {len(drop)} similar <{label}> "))
            for d in drop:
                d.decompose()

    # T3 — data-*/aria-* 값 cap (class/id/href/src 불가침).
    for el in soup.find_all(True):
        if el.name is None:
            continue
        attrs = getattr(el, "attrs", None)
        if not attrs:
            continue
        for k in list(attrs):
            kl = str(k).lower()
            if not (kl.startswith("data-") or kl.startswith("aria-")):
                continue
            v = attrs[k]
            if isinstance(v, str) and len(v) > attr_cap and not v.isdigit():
                attrs[k] = v[:attr_cap] + "…"

    # T2 — 긴 text 노드 cap (<a> 자손 제외 — 제목/post_id 소스).
    for node in list(soup.find_all(string=True)):
        if isinstance(node, Comment):
            continue
        s = str(node)
        if len(s) <= text_cap or node.find_parent("a") is not None:
            continue
        node.replace_with(s[:text_cap] + "…")

    out = str(soup.body or soup)
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n[ \t]+", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_text(path: Optional[str | Path]) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _pick_list_result(results: list[dict]) -> Optional[dict]:
    ok = [r for r in results if r.get("target") == "list" and r.get("classification") == "OK"]
    if not ok:
        return None
    # headless(S4) 우선 — 렌더 후 HTML 이라 더 완전함
    ok.sort(key=lambda r: (0 if str(r.get("strategy", "")).startswith("S4") else 1,))
    return ok[0]


def _pick_article_result(results: list[dict]) -> Optional[dict]:
    ok = [r for r in results if r.get("target") == "article" and r.get("classification") == "OK"]
    if not ok:
        return None
    ok.sort(key=lambda r: (0 if str(r.get("strategy", "")).startswith("S4") else 1,))
    return ok[0]


def _condense_matrix(results: list[dict]) -> list[dict]:
    out = []
    for r in results:
        out.append({
            "strategy": r.get("strategy"),
            "target": r.get("target"),
            "status": r.get("status"),
            "classification": r.get("classification"),
            "notable": (r.get("notable") or [])[:3],
        })
    return out


def _list_body_path(out_dir: Path, results: list[dict]) -> Optional[Path]:
    lr = _pick_list_result(results)
    if lr and lr.get("body_path"):
        p = Path(lr["body_path"])
        if p.exists():
            return p
    # fallback: headless list.html, 그다음 s1.*.html
    for name in ["list.html", "list.captured.html"]:
        p = out_dir / name
        if p.exists():
            return p
    for p in sorted(out_dir.glob("s1.*.html")):
        return p
    return None


def _article_body_path(out_dir: Path, results: list[dict]) -> Optional[Path]:
    """글 본문 HTML 샘플 경로.

    클릭 진입(article_click.html)이 성공했으면 그게 가장 신뢰도 높다 — 목록에서 *실제로 클릭했을 때* 가는 페이지라,
    직접 GET 하면 다른 데로 튕기는 클라이언트 라우트(마비노기모바일류)에서 직접-GET 결과(엉뚱한 페이지)보다 정확하다.
    그 외엔 정적 fetch / headless 렌더(article.html) / register 의 re-probe(article.html 덮어씀) 중 *가장 큰* 파일을 고른다
    (SPA 껍데기보다 렌더된 DOM 이 크므로)."""
    cm = _read_json(out_dir / "article_click.json") or {}
    click_p = out_dir / "article_click.html"
    note = str(cm.get("note") or "")
    click_result_ok = any(r.get("strategy") == "S4.click" and r.get("classification") == "OK" for r in results)

    def _strip_url(u: object) -> str:
        return str(u or "").split("#")[0].rstrip("/").lower()

    click_ok = (click_result_ok and click_p.is_file() and click_p.stat().st_size > 2000
                and bool(cm.get("resolved_url"))
                and _strip_url(cm.get("resolved_url")) != _strip_url(cm.get("requested_url"))   # 클릭했는데 목록 URL 그대로면(=글 페이지 아님) 제외
                and "후보 없음" not in note and "클릭 실패" not in note)
    cands: list[Path] = []
    if click_ok:
        cands.append(click_p)
    ar = _pick_article_result(results)
    if ar and ar.get("body_path"):
        p = Path(ar["body_path"])
        if p.exists() and p not in cands:
            cands.append(p)
    # NOTE: article_click.html 은 click_ok 일 때만 후보로 — 클릭이 OK 가 아니었으면(엉뚱한 링크 클릭 등) 신뢰 안 함.
    for name in ("article.html", "article.captured.html", "article"):
        p = out_dir / name
        if p.is_file() and p not in cands:
            cands.append(p)
    cands = [p for p in cands if p.is_file()]
    if not cands:
        return None
    if click_ok:
        return click_p
    return max(cands, key=lambda p: p.stat().st_size)


def _hydration_digest(raw_list_html: str) -> dict:
    """raw 목록 HTML 에서 __NEXT_DATA__/__NUXT__/__INITIAL_STATE__ 추출 → truncate."""
    if not raw_list_html or extract_hydration is None:
        return {}
    try:
        blobs = extract_hydration(raw_list_html)
    except Exception:
        return {}
    out: dict[str, Any] = {}
    for key, blob in (blobs or {}).items():
        try:
            s = json.dumps(blob, ensure_ascii=False)
        except Exception:
            s = str(blob)
        if len(s.encode("utf-8")) > HYDRATION_MAX_BYTES:
            s = s.encode("utf-8")[:HYDRATION_MAX_BYTES].decode("utf-8", errors="ignore") + " …[truncated]"
        out[key] = s
    return out


def _backfill_missing_heuristics(list_cands: dict, *, base_url: Optional[str]) -> None:
    """list_candidates.json 의 누락 휴리스틱 키 자동 보강 — 옛 artifact 호환.

    artifact 파일은 안 건드림. digest 의 list_cands dict 안에만 박음. 호출 자리:
    `build_digest` 의 list_cands 로드 직후. 입력 = artifact 의 *이미 있는* 키만 (휴리스틱이
    artifact 재실행 없이 재호출 가능 — html_repeating_patterns 같은 base 키는 옛 artifact 에도 있음).

    미래 같은 자리 휴리스틱 추가 시 이 함수에 한 줄 더. 옛 artifact 자동 호환.
    """
    if not isinstance(list_cands, dict) or not base_url:
        return
    # root_marketing_homepage — 2026-05-19 추가. 입력: base_url + html_repeating_patterns +
    # nav_only_same_host + body_empty_likely (모두 옛 artifact 에도 있는 base 키).
    if "root_marketing_homepage" not in list_cands:
        try:
            from probe.extract import root_marketing_homepage  # noqa: PLC0415
            list_cands["root_marketing_homepage"] = root_marketing_homepage(
                base_url=base_url,
                html_candidates=list_cands.get("html_repeating_patterns") or [],
                nav_only_same_host=list_cands.get("nav_only_same_host"),
                body_empty_likely=bool(list_cands.get("body_empty_likely") or False),
            )
        except Exception:  # noqa: BLE001
            # 보강 실패 = 그냥 키 없음 (None). 게이트는 안 잡지만 다른 게이트 / LLM 으로 계속.
            list_cands["root_marketing_homepage"] = None


def _host_label(host: str) -> str:
    host = (host or "").lower().split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    parts = [p for p in host.split(".") if p]
    if len(parts) >= 2:
        return parts[-2]
    return parts[0] if parts else ""


def _same_host(url: object, page_host: str) -> bool:
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return False
    try:
        return urlsplit(url).netloc.lower().split(":", 1)[0] == page_host
    except ValueError:
        return False


def _validated_feed_candidates(digest: dict) -> list[dict]:
    out: list[dict] = []
    for c in digest.get("feed_candidates") or []:
        if not isinstance(c, dict):
            continue
        if c.get("validated") is not True:
            continue
        if (c.get("item_count") or 0) <= 0:
            continue
        if c.get("root_tag") not in ("rss", "feed"):
            continue
        out.append(c)
    return out


def _html_same_host_row_count(digest: dict) -> int:
    page = digest.get("url") or ""
    try:
        page_host = urlsplit(page).netloc.lower().split(":", 1)[0]
    except ValueError:
        page_host = ""
    if not page_host:
        return 0
    total = 0
    lc = digest.get("list_candidates") or {}
    for c in lc.get("html_repeating_patterns") or []:
        if not isinstance(c, dict):
            continue
        sample = c.get("sample_url") or c.get("href_pattern_guess")
        if not sample or not _same_host(sample, page_host):
            continue
        sel = str(c.get("selector") or "").lower()
        sel_root = sel.split(">", 1)[0].strip() if ">" in sel else sel.strip()
        if sel_root in ("head", "nav", "footer", "header", "aside"):
            continue
        if any(tok in sel for tok in ("> meta", "> link", "> script", "> style", "> svg", "> path")):
            continue
        try:
            n = int(c.get("child_count") or c.get("count") or 1)
        except (TypeError, ValueError):
            n = 1
        total += max(n, 0)
    return total


def _site_kind_js_signal(digest: dict) -> bool:
    hay = " ".join(str(x or "") for x in (
        digest.get("verdict"),
        digest.get("recommended_strategy"),
        " ".join(digest.get("notes") or []),
    )).lower()
    return any(tok in hay for tok in (
        "playwright", "javascript", "spa", "nuxt", "next.js", "__next_data__", "nextjs",
        "hydration", "빈 shell", "empty shell", "렌더", "render delta",
    ))


def _semantic_feed_match(digest: dict, feeds: list[dict]) -> bool:
    page = digest.get("url") or ""
    try:
        sp = urlsplit(page)
    except ValueError:
        return False
    page_host = sp.netloc.lower().split(":", 1)[0]
    host_label = _host_label(page_host)
    page_prefix = (sp.scheme + "://" + sp.netloc + (sp.path or "/")).rstrip("/")
    page_prefix = page_prefix.rsplit("/", 1)[0] if "/" in page_prefix else page_prefix

    for feed in feeds:
        title = re.sub(r"[^a-z0-9]+", "", str(feed.get("title") or "").lower())
        if host_label and host_label in title:
            return True
        urls: list[object] = []
        for key in ("first_item_url", "first_item_link", "sample_item_url", "sample_link"):
            if feed.get(key):
                urls.append(feed.get(key))
        for key in ("item_urls", "item_links", "sample_item_urls"):
            if isinstance(feed.get(key), list):
                urls.extend(feed.get(key) or [])
        for u in urls[:5]:
            if isinstance(u, str) and u.startswith(page_prefix):
                return True
    return False


def classify_site_kind(digest: dict) -> dict:
    """Classify the digest's primary acquisition shape for prompt/enforcement hints."""
    feeds, link_rel_feeds = _validated_or_linked_feeds(digest)
    primary = feeds[0].get("url") if feeds else None
    rows = _html_same_host_row_count(digest)
    lc = digest.get("list_candidates") or {}
    audio = lc.get("audio_share_host_detected") or {}
    structural_audio = (
        isinstance(audio, dict)
        and bool(audio.get("audio_share_host_detected") or audio.get("detected"))
        and audio.get("confidence") == "structural"
    )
    semantic = _semantic_feed_match(digest, feeds)
    js_signal = _site_kind_js_signal(digest)

    link_rel_primary = link_rel_feeds[0].get("url") if link_rel_feeds else None

    evidence: list[str] = []
    if feeds:
        evidence.append("feed_semantics:item_count>0")
    if link_rel_feeds:
        evidence.append("rss_feed_urls:link_rel")
    if rows:
        evidence.append(f"html_same_host_rows:{rows}")
    if structural_audio:
        evidence.append("audio_share:structural")
    elif isinstance(audio, dict) and audio.get("confidence") == "host_known":
        evidence.append("audio_share:host_known")
    if semantic:
        evidence.append("semantic_match:high")
    if js_signal:
        evidence.append("js_render_signal")

    # validated feed 우선 (high confidence)
    if feeds and structural_audio:
        return {"kind": "podcast", "confidence": "high", "evidence": evidence, "primary_feed_url": primary}
    if feeds and rows >= 5 and (semantic or rows >= 10):
        conf = "high" if semantic else "med"
        return {"kind": "hybrid", "confidence": conf, "evidence": evidence, "primary_feed_url": primary}
    if feeds and rows < 3:
        return {"kind": "rss", "confidence": "high", "evidence": evidence, "primary_feed_url": primary}
    # link_rel 만 있는 경우 (옛 probe artifact validate 안 됨) — med confidence, F enforcement 작동 X
    if link_rel_feeds and structural_audio:
        return {"kind": "podcast", "confidence": "med", "evidence": evidence, "primary_feed_url": link_rel_primary}
    if link_rel_feeds and rows < 3:
        return {"kind": "rss", "confidence": "med", "evidence": evidence, "primary_feed_url": link_rel_primary}
    if link_rel_feeds and rows >= 5:
        return {"kind": "hybrid", "confidence": "med", "evidence": evidence, "primary_feed_url": link_rel_primary}
    # feed 신호 없음
    if rows >= 5 and not feeds and not link_rel_feeds and not js_signal:
        conf = "high" if rows >= 10 else "med"
        return {"kind": "static_html", "confidence": conf, "evidence": evidence}
    if rows < 3 and js_signal and not feeds and not link_rel_feeds:
        return {"kind": "spa_rendered", "confidence": "high", "evidence": evidence}
    return {"kind": "unknown", "confidence": "low", "evidence": evidence}


def _validated_or_linked_feeds(digest: dict) -> tuple[list[dict], list[dict]]:
    """Return fetch-validated feed candidates separately from unvalidated link-rel hints."""
    validated_feeds = _validated_feed_candidates(digest)
    link_rel: list[dict] = []
    lc = digest.get("list_candidates") or {}
    if not validated_feeds:
        for f in lc.get("rss_feed_urls") or []:
            if not isinstance(f, dict):
                continue
            if f.get("validated") is True:
                validated_feeds.append(f)
            else:
                link_rel.append(f)
    return validated_feeds, link_rel


def build_digest(
    *,
    slug: Optional[str] = None,
    url: Optional[str] = None,
    probe_dir: Optional[str | Path] = None,
    max_html_bytes: int = DEFAULT_MAX_HTML_BYTES,
) -> dict:
    if probe_dir is not None:
        out_dir = Path(probe_dir)
        if slug is None:
            slug = out_dir.name
    else:
        if slug is None and url is not None:
            slug = url_to_slug(url)
        if slug is None:
            raise ValueError("slug / url / probe_dir 중 하나는 필요")
        out_dir = output_dir(slug)

    if not out_dir.exists():
        raise FileNotFoundError(f"probe 산출물 디렉토리 없음: {out_dir}  (먼저 `python scripts/probe.py \"<URL>\" --lite` 실행)")

    diag = _read_json(out_dir / "diagnosis.json") or {}
    robots = _read_json(out_dir / "robots.json") or {}
    list_cands = _read_json(out_dir / "list_candidates.json") or {}
    feeds = _read_json(out_dir / "feed_candidates.json") or {}
    sitemap_disc = _read_json(out_dir / "sitemap.json") or {}
    captured_headers = _read_json(out_dir / "list.captured_headers.json") or {}
    article_body_apis = _read_json(out_dir / "article_candidates.json")  # register.py 의 글페이지 re-probe 가 씀 (없으면 None)
    click_meta = _read_json(out_dir / "article_click.json") or {}        # probe Phase 9b: 목록에서 글 링크 클릭 → 최종 URL/페이지
    results = diag.get("results") or []

    # 누락 휴리스틱 키 자동 보강 — 옛 artifact 호환 (post-fix-cleanup 의 핵심).
    # list_candidates.json 의 *기존 키* 만 입력으로 받는 휴리스틱은 artifact 재실행 없이 재호출 가능.
    # 디스크 X — digest 의 list_cands dict 안에만 박음. 미래 같은 자리 휴리스틱 추가 시 같은 패턴.
    _backfill_missing_heuristics(list_cands, base_url=diag.get("url") or url)

    # 통과한 정적 프리셋의 request 헤더
    static_ok = next((r for r in results if r.get("target") == "list"
                      and r.get("classification") == "OK"
                      and str(r.get("strategy", "")).startswith("S1")), None)
    static_ok_headers = (static_ok or {}).get("headers") if static_ok else None
    static_ok_preset = (static_ok or {}).get("strategy") if static_ok else None

    list_path = _list_body_path(out_dir, results)
    raw_list_html = _read_text(list_path)
    list_html_clean, list_trunc = clean_html(raw_list_html, max_bytes=max_html_bytes)

    article_path = _article_body_path(out_dir, results)
    raw_article_html = _read_text(article_path)
    article_html_clean, article_trunc = clean_html(raw_article_html, max_bytes=max_html_bytes)

    hydration = _hydration_digest(raw_list_html)

    digest = {
        "slug": slug,
        "url": diag.get("url") or url,
        "verdict": diag.get("verdict"),
        "recommended_strategy": diag.get("recommended_strategy"),
        "recommended_headers": diag.get("recommended_headers"),
        "recommended_polling_interval_sec": diag.get("recommended_polling_interval_sec"),
        "article_entry_ok": diag.get("article_entry_ok"),
        "notes": diag.get("notes") or [],
        "robots": {
            "status": robots.get("status"),
            "crawl_delay": robots.get("crawl_delay"),
            "disallow": robots.get("disallow") or [],
        },
        "entry_matrix": _condense_matrix(results),
        "static_ok_preset": static_ok_preset,
        "static_ok_request_headers": static_ok_headers,
        "captured_headers": captured_headers or None,
        "list_candidates": list_cands,
        "hydration": hydration or None,
        "feed_candidates": (feeds.get("candidates") if isinstance(feeds, dict) else feeds) or [],
        "sitemap_candidates": (sitemap_disc.get("candidates") if isinstance(sitemap_disc, dict) else []) or [],
        # α minimal (2026-05-24): MDR `list_candidates` 후보. measurement-only — prompt 에서 *읽지 않음*
        # (`prompts/config_writer.system.txt` 가 이 키 모름). 1주 운영 후 noise 평가로 prompt 통합 여부 결정.
        # docs/2026-05-24-layer-addition-plan.md A 묶음 #4.
        "mdr_candidates": _mdr_candidates_safe(raw_list_html),
        # θ minimal (2026-05-24): sitemap-only-fit signal. canva/salesforce 처럼 sitemap 만으로 polling
        # 가능한 사이트 분류 signal. measurement-only — prompt 안 읽음. A 묶음 #5.
        "sitemap_only_fit_signal": _sitemap_only_fit_signal(
            (sitemap_disc.get("candidates") if isinstance(sitemap_disc, dict) else []) or []
        ),
        "list_html": {
            "source": str(list_path) if list_path else None,
            "truncated": list_trunc,
            "html": list_html_clean,
        },
        "article_sample": {
            "url": (list_cands.get("first_article_url") if isinstance(list_cands, dict) else None),
            "source": str(article_path) if article_path else None,
            "truncated": article_trunc,
            "html": article_html_clean,
            # 글 페이지가 SPA 라서 정적 HTML 본문이 비어있을 때 register.py 의 re-probe 가 채우는 본문 JSON API 후보 (없으면 None)
            "api_candidates": (article_body_apis if isinstance(article_body_apis, list) and article_body_apis else None),
            # probe Phase 9b: 목록에서 글 링크를 실제로 클릭했을 때 간 최종 URL (직접 GET 한 first_article_url 과 다르면 클라이언트 라우트)
            "clicked_resolved_url": click_meta.get("resolved_url"),
            "clicked_note": click_meta.get("note"),
        },
        # NOTE: 글 샘플은 현재 1개(probe 가 first_article_url / 클릭 진입 1건만 fetch). 2~3개 확장은 추후 probe 보강 때.
    }
    digest["site_kind"] = classify_site_kind(digest)

    # 클릭 진입 URL 이 직접 GET URL 과 다르면(클라이언트 라우트) — 또는 애초에 href 가 없었으면 — 강하게 알린다.
    # 단, 클릭 결과가 OK 로 분류됐을 때만 (UNKNOWN_ERROR 면 엉뚱한 링크를 클릭했을 수 있음 → 잘못된 hint 를 주지 않는다).
    resolved = click_meta.get("resolved_url")
    first_au = list_cands.get("first_article_url") if isinstance(list_cands, dict) else None
    click_result_ok = any(r.get("strategy") == "S4.click" and r.get("classification") == "OK" for r in results)
    if resolved and click_result_ok:
        def _norm(u: Optional[str]) -> str:
            return (u or "").split("#")[0].rstrip("/").lower()
        notes = list(digest.get("notes") or [])
        if first_au and _norm(resolved) != _norm(first_au):
            notes.append(
                f"⚠ 목록의 글 링크({first_au})를 직접 GET 하면 다른 페이지로 가지만, 목록에서 *클릭*하면 {resolved} 로 간다 "
                f"— 클라이언트 사이드 라우트. handwritten config 에서 article.url_template(또는 list.fields.url)을 {resolved} 형태로 "
                f"(URL 안 숫자 ID 를 {{post_id}} 로). article_sample.html 은 이미 그 클릭 후 페이지다."
            )
        elif not first_au:
            notes.append(
                f"목록의 글 링크가 href 없이 JS 로 동작 — 클릭하면 {resolved} 로 간다. article_sample.html 은 그 페이지. "
                f"post_id 는 그 URL, 또는 list_candidates.html_repeating_patterns[].row_data_attrs / inline_js_data_candidates 에서."
            )
        digest["notes"] = notes
    return digest


def _summary_line(digest: dict) -> str:
    lh = digest.get("list_html") or {}
    ah = digest.get("article_sample") or {}
    lc = digest.get("list_candidates") or {}
    n_html = len(lc.get("html_repeating_patterns") or [])
    n_json = len(lc.get("traffic_json_api_candidates") or [])
    n_hyd = len(lc.get("hydration_list_candidates") or [])
    n_ijs = len(lc.get("inline_js_data_candidates") or [])
    n_rid = len(lc.get("runtime_id_candidates") or [])
    clicked = ah.get("clicked_resolved_url")
    return (
        f"verdict={digest.get('verdict')!r}  recommended={digest.get('recommended_strategy')!r}\n"
        f"  list_html: {len((lh.get('html') or '').encode('utf-8'))} bytes (truncated={lh.get('truncated')})  src={lh.get('source')}\n"
        f"  article_html: {len((ah.get('html') or '').encode('utf-8'))} bytes (truncated={ah.get('truncated')})  src={ah.get('source')}\n"
        f"  candidates: html={n_html} json_api={n_json} hydration={n_hyd} inline_js={n_ijs} runtime_ids={n_rid}  first_article={lc.get('first_article_url')}"
        + (f"  clicked→{clicked}" if clicked else "") + "\n"
        f"  robots: crawl_delay={digest['robots'].get('crawl_delay')}  disallow={len(digest['robots'].get('disallow') or [])}건\n"
        f"  captured_headers={'yes' if digest.get('captured_headers') else 'no'}  static_ok_preset={digest.get('static_ok_preset')}  hydration_keys={list((digest.get('hydration') or {}).keys())}"
    )


def main(argv) -> int:
    p = argparse.ArgumentParser(description="probe 산출물 → gemini 입력 digest")
    p.add_argument("slug", nargs="?", help="probe slug (output/probe/<slug>/)")
    p.add_argument("--url", help="URL (slug 대신; url_to_slug 로 변환)")
    p.add_argument("--probe-dir", help="probe 산출물 디렉토리 직접 지정")
    p.add_argument("--out", help="digest JSON 저장 경로 (없으면 요약만 출력)")
    p.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_HTML_BYTES, help="정제 HTML 최대 바이트")
    p.add_argument("--print", action="store_true", help="digest JSON 전체를 stdout 으로")
    args = p.parse_args(argv)

    if not (args.slug or args.url or args.probe_dir):
        p.error("slug 또는 --url 또는 --probe-dir 필요")

    digest = build_digest(slug=args.slug, url=args.url, probe_dir=args.probe_dir, max_html_bytes=args.max_bytes)
    print(f"[digest] {digest.get('slug')}  ({digest.get('url')})")
    print(_summary_line(digest))
    if args.out:
        Path(args.out).write_text(json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  → {args.out}")
    if args.print:
        print(json.dumps(digest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
