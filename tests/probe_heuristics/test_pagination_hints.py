"""URL pagination hint extraction — probe.extract.pagination_hints.

정적 HTML anchor 의 ?page=N + HAR XHR fetch URL 의 ?page=N 양쪽 신호. Radiolab 류 SPA 의
page query 봉합용 (2026-05-25 plan 후속).
"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory


covers = ["pagination_hints"]


def _make_har(tmp_dir: Path, entries: list[dict]) -> Path:
    """간단 HAR 파일 생성. entries = [{url, resourceType}, ...]."""
    har = {"log": {"entries": []}}
    for e in entries:
        har["log"]["entries"].append({
            "_resourceType": e.get("resourceType", "xhr"),
            "request": {"url": e["url"], "method": e.get("method", "GET")},
            "response": {"status": 200, "headers": [], "content": {"mimeType": "application/json"}},
        })
    har_path = tmp_dir / "traffic.list.har"
    har_path.write_text(json.dumps(har), encoding="utf-8")
    return har_path


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import pagination_hints, _pagination_url_template

    cases: list[tuple[str, bool, str]] = []

    # 1. HTML anchor pagination (단순) — <a href="?page=2"> 박혀있는 정적 사이트
    html_anchor = """
    <html><body>
      <a href="?page=1">1</a>
      <a href="?page=2">2</a>
      <a href="?page=3">3</a>
    </body></html>
    """
    out = pagination_hints(html=html_anchor, base_url="https://x.com/board")
    cases.append(("html_anchor_detected", len(out) >= 1, f"got {out!r}"))
    if out:
        cases.append(("html_anchor_param_page", out[0]["param"] == "page", f"got {out[0]!r}"))
        cases.append(("html_anchor_template",
                      out[0]["url_template"] == "https://x.com/board?page={page}",
                      f"got {out[0].get('url_template')!r}"))
        cases.append(("html_anchor_source", out[0]["source"] == "html_anchor", ""))

    # 2. HAR XHR pagination (Radiolab 류 — SPA fetch URL)
    with TemporaryDirectory() as td:
        td_p = Path(td)
        har = _make_har(td_p, [
            {"url": "https://api.wnyc.org/api/v3/channel/shows/radiolab/recent_stories/1?limit=12&page=1",
             "resourceType": "xhr"},
            {"url": "https://api.wnyc.org/api/v3/channel/shows/radiolab/recent_stories/2?limit=12&page=2",
             "resourceType": "xhr"},
        ])
        out_har = pagination_hints(html="", base_url="https://radiolab.org/podcast", har_path=har)
        cases.append(("har_xhr_detected", len(out_har) >= 1, f"got {out_har!r}"))
        if out_har:
            # XHR 의 page param → base_url 의 path 에 `?page={page}` 박기
            cases.append(("har_xhr_template_uses_base_url",
                          out_har[0]["url_template"] == "https://radiolab.org/podcast?page={page}",
                          f"got {out_har[0].get('url_template')!r}"))
            cases.append(("har_xhr_source", out_har[0]["source"] == "har_xhr", ""))

    # 3. 둘 다 — anchor 우선 (먼저 들어옴), XHR 도 같이
    with TemporaryDirectory() as td:
        td_p = Path(td)
        har = _make_har(td_p, [
            {"url": "https://api.x.com/items?page=1", "resourceType": "xhr"},
        ])
        html_both = '<html><body><a href="?p=2">2</a></body></html>'
        out_both = pagination_hints(html=html_both, base_url="https://x.com/list", har_path=har)
        params = [h["param"] for h in out_both]
        cases.append(("both_sources_present", "p" in params and "page" in params,
                      f"got params={params!r}"))

    # 4. 빈 신호 — html 없고 HAR 도 없으면 빈 list
    cases.append(("empty_returns_empty",
                  pagination_hints(html="", base_url="https://x.com/") == [], ""))

    # 5. _pagination_url_template — param 자리 치환
    tmpl = _pagination_url_template("https://x.com/list?page=5&sort=desc", "page")
    cases.append(("url_template_replaces_param",
                  tmpl == "https://x.com/list?page={page}&sort=desc",
                  f"got {tmpl!r}"))
    cases.append(("url_template_no_param_returns_none",
                  _pagination_url_template("https://x.com/list?sort=desc", "page") is None, ""))

    # 6. ad/tracker XHR skip
    with TemporaryDirectory() as td:
        td_p = Path(td)
        har = _make_har(td_p, [
            {"url": "https://googletagmanager.com/gtm.js?id=1&page=2", "resourceType": "xhr"},
            {"url": "https://x.com/api/items?page=1", "resourceType": "xhr"},
        ])
        out_skip = pagination_hints(html="", base_url="https://x.com/list", har_path=har)
        # ad/tracker 는 skip, x.com 만 잡혀야
        sources_urls = [h["evidence_url"] for h in out_skip]
        cases.append(("ad_tracker_xhr_skipped",
                      not any("googletagmanager" in u for u in sources_urls),
                      f"got {sources_urls!r}"))

    # 7. resource type 이 xhr/fetch 아니면 skip (image 등)
    with TemporaryDirectory() as td:
        td_p = Path(td)
        har = _make_har(td_p, [
            {"url": "https://x.com/img?page=1", "resourceType": "image"},
            {"url": "https://x.com/api?page=1", "resourceType": "fetch"},
        ])
        out_rt = pagination_hints(html="", base_url="https://x.com/", har_path=har)
        cases.append(("non_xhr_skipped",
                      all(h["source"] == "har_xhr" and "img" not in h["evidence_url"]
                          for h in out_rt),
                      f"got {out_rt!r}"))

    # 8. path_segment pagination — `/news/page/2`·`/news/page/3` 정적 archive
    #    (atlus.co.jp/news/, fate-go.jp/news/ 류 — 2026-05-26 games-jp batch).
    from probe.extract import _pagination_path_template
    html_path_seg = """
    <html><body>
      <a href="/news/page/2">2</a>
      <a href="/news/page/3">3</a>
      <a href="/news/page/163">163</a>
    </body></html>
    """
    out_ps = pagination_hints(html=html_path_seg, base_url="https://www.atlus.co.jp/news/")
    path_seg_hints = [h for h in out_ps if h.get("kind") == "path_segment"]
    cases.append(("path_segment_detected", len(path_seg_hints) >= 1, f"got {out_ps!r}"))
    if path_seg_hints:
        cases.append(("path_segment_template",
                      path_seg_hints[0]["url_template"] == "https://www.atlus.co.jp/news/page/{page}",
                      f"got {path_seg_hints[0]!r}"))
        cases.append(("path_segment_param_page", path_seg_hints[0]["param"] == "page", ""))

    # 9. path_segment requires ≥2 distinct page numbers OR pager-class wrapper.
    # 9a. 단일 link + pager-class wrapper 없음 → 거부
    html_single_page = '<html><body><a href="/news/page/2">2</a></body></html>'
    out_single = pagination_hints(html=html_single_page, base_url="https://x.com/news/")
    cases.append(("path_segment_single_page_no_wrapper_rejected",
                  not any(h.get("kind") == "path_segment" for h in out_single),
                  f"got {out_single!r}"))
    # 9b. 단일 link 인데 `class="pager"` 안 → 허용 (fate-go 류 Next→ only).
    html_pager_wrapper = """
    <html><body>
      <div class="pager">
        <p class="prev"><a href="/page/2/">次へ »</a></p>
      </div>
    </body></html>
    """
    out_pw = pagination_hints(html=html_pager_wrapper, base_url="https://www.fate-go.jp/news/")
    pager_hints = [h for h in out_pw if h.get("kind") == "path_segment"]
    cases.append(("path_segment_pager_class_single_accepted", len(pager_hints) >= 1, f"got {out_pw!r}"))
    if pager_hints:
        cases.append(("path_segment_pager_class_template",
                      pager_hints[0]["url_template"] == "https://www.fate-go.jp/page/{page}/",
                      f"got {pager_hints[0]!r}"))

    # 10. path_segment cross-host skip — `/page/N` 에 다른 host 인 link 는 collect X
    html_cross_host = """
    <html><body>
      <a href="https://other.com/news/page/2">2</a>
      <a href="https://other.com/news/page/3">3</a>
    </body></html>
    """
    out_cross = pagination_hints(html=html_cross_host, base_url="https://x.com/news/")
    cases.append(("path_segment_cross_host_skipped",
                  not any(h.get("kind") == "path_segment" for h in out_cross),
                  f"got {out_cross!r}"))

    # 11. trailing slash 보존 — `/page/2/` → template `/page/{page}/`
    html_trail = """
    <html><body>
      <a href="/page/2/">2</a>
      <a href="/page/3/">3</a>
    </body></html>
    """
    out_trail = pagination_hints(html=html_trail, base_url="https://x.com/")
    trail_hints = [h for h in out_trail if h.get("kind") == "path_segment"]
    cases.append(("path_segment_trailing_slash_preserved",
                  trail_hints and trail_hints[0]["url_template"].endswith("/page/{page}/"),
                  f"got {trail_hints!r}"))

    # 12. _pagination_path_template helper
    cases.append(("path_template_basic",
                  _pagination_path_template("https://x.com/news/page/2") == "https://x.com/news/page/{page}",
                  ""))
    cases.append(("path_template_no_match_returns_none",
                  _pagination_path_template("https://x.com/news/") is None, ""))

    return cases
