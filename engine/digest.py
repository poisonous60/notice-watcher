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

from bs4 import BeautifulSoup, Comment


# probe 패키지 import 를 위해 프로젝트 루트가 sys.path 에 있어야 함.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

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
    """글 본문 HTML 샘플 경로. 정적 fetch 결과 / headless 렌더(article.html) / register 의 re-probe(article.html 덮어씀)
    중 *가장 큰* 파일을 고른다 — SPA 껍데기보다 렌더된 DOM 이 크므로 그게 본문 selector 잡기에 낫다."""
    cands: list[Path] = []
    ar = _pick_article_result(results)
    if ar and ar.get("body_path"):
        p = Path(ar["body_path"])
        if p.exists():
            cands.append(p)
    for name in ("article.html", "article.captured.html", "article"):
        p = out_dir / name
        if p.is_file() and p not in cands:
            cands.append(p)
    cands = [p for p in cands if p.is_file()]
    if not cands:
        return None
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
    captured_headers = _read_json(out_dir / "list.captured_headers.json") or {}
    article_body_apis = _read_json(out_dir / "article_candidates.json")  # register.py 의 글페이지 re-probe 가 씀 (없으면 None)
    results = diag.get("results") or []

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
        },
        # NOTE: 글 샘플은 현재 1개(probe 가 first_article_url 만 fetch). 2~3개 확장은 추후 probe 보강 때.
    }
    return digest


def _summary_line(digest: dict) -> str:
    lh = digest.get("list_html") or {}
    ah = digest.get("article_sample") or {}
    lc = digest.get("list_candidates") or {}
    n_html = len(lc.get("html_repeating_patterns") or [])
    n_json = len(lc.get("traffic_json_api_candidates") or [])
    n_hyd = len(lc.get("hydration_list_candidates") or [])
    return (
        f"verdict={digest.get('verdict')!r}  recommended={digest.get('recommended_strategy')!r}\n"
        f"  list_html: {len((lh.get('html') or '').encode('utf-8'))} bytes (truncated={lh.get('truncated')})  src={lh.get('source')}\n"
        f"  article_html: {len((ah.get('html') or '').encode('utf-8'))} bytes (truncated={ah.get('truncated')})  src={ah.get('source')}\n"
        f"  candidates: html={n_html} json_api={n_json} hydration={n_hyd}  first_article={lc.get('first_article_url')}\n"
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
