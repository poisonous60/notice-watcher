"""probe.discover._body_is_feed — fetch 한 page 본문 RSS/Atom/RDF content-sniff.

`_looks_like_feed_url` (path 휴리스틱) 가 못 잡는 직접-피드 URL (path 모양 무관) 을
본문 root 태그로 검출. board_shape false-reject 회피 (2026-05-20-b batch:
hnrss.org/newest · phoronix.com/rss.php · gamespot.com/feeds/news/).
"""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from probe.discover import _body_is_feed, _looks_like_feed_url

    cases: list[tuple[str, bool, str]] = []

    # 1. rss 본문 (xml decl 없이) — feed
    out = _body_is_feed('<rss version="2.0"><channel><title>x</title></channel></rss>')
    cases.append(("rss_no_decl", out is True, f"got {out!r}"))

    # 2. xml decl + rss — feed
    out = _body_is_feed('<?xml version="1.0"?>\n<rss version="2.0"><channel></channel></rss>')
    cases.append(("rss_with_decl", out is True, f"got {out!r}"))

    # 3. atom feed — feed
    out = _body_is_feed('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>x</title></feed>')
    cases.append(("atom_feed", out is True, f"got {out!r}"))

    # 4. RDF (RSS 1.0) — feed
    out = _body_is_feed('<?xml version="1.0"?><rdf:RDF xmlns="http://purl.org/rss/1.0/"><channel/></rdf:RDF>')
    cases.append(("rdf_rss10", out is True, f"got {out!r}"))

    # 5. 앞 공백 있는 본문 — lstrip 후 검출
    out = _body_is_feed('   \n  <?xml version="1.0"?><rss version="2.0">')
    cases.append(("leading_ws", out is True, f"got {out!r}"))

    # 6. HTML 페이지 — feed 아님 (false positive 차단)
    out = _body_is_feed('<!DOCTYPE html><html><head><title>x</title></head><body>hi</body></html>')
    cases.append(("html_not_feed", out is False, f"got {out!r}"))

    # 7. 빈 본문 — feed 아님
    out = _body_is_feed("")
    cases.append(("empty_not_feed", out is False, f"got {out!r}"))

    # 8. xml decl 만 (rss/feed 태그 없음) — feed 아님
    out = _body_is_feed('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/"></urlset>')
    cases.append(("xml_sitemap_not_feed", out is False, f"got {out!r}"))

    # 8a. Chromium XML-viewer 래퍼 (headless 렌더 결과) — 원본 rss 가 안에 박힘 → feed
    chromium = ('<html xmlns="http://www.w3.org/1999/xhtml"><head>'
                '<style id="xml-viewer-style">/* ... */</style></head><body>'
                '<div id="webkit-xml-viewer-source-xml"><rss version="2.0"><channel/></rss></div></body></html>')
    out = _body_is_feed(chromium)
    cases.append(("chromium_xml_viewer_rss", out is True, f"got {out!r}"))

    # 8b. Chromium XML-viewer 래퍼인데 안이 sitemap (rss 아님) — feed 아님
    chromium_sm = ('<html><head><style id="xml-viewer-style"></style></head><body>'
                   '<div id="webkit-xml-viewer-source-xml"><urlset></urlset></div></body></html>')
    out = _body_is_feed(chromium_sm)
    cases.append(("chromium_xml_viewer_sitemap_not_feed", out is False, f"got {out!r}"))

    # 9. content-sniff 가 path 휴리스틱 gap 을 메우는지 — 직접-피드 URL path 는 매칭 X (회귀 가드)
    cases.append(("hnrss_url_shape_miss", _looks_like_feed_url("https://hnrss.org/newest") is False,
                  "hnrss /newest path 는 _looks_like_feed_url 가 못 잡음 (body sniff 가 필요한 이유)"))
    cases.append(("phoronix_url_shape_miss", _looks_like_feed_url("https://www.phoronix.com/rss.php") is False,
                  "phoronix /rss.php path 는 _looks_like_feed_url 가 못 잡음"))

    # 10~13. _has_verified_feed — HTML BLOCKED 라도 fetch-검증 피드면 등록 진행 (register.py).
    from scripts.register import _has_verified_feed
    cases.append(("verified_well_known_xml",
                  _has_verified_feed({"feed_candidates": [
                      {"source": "well-known-path", "status": 200, "content_type": "application/xml"}]}) is True,
                  "well-known 200 xml = 검증됨"))
    cases.append(("verified_input_url_fetch",
                  _has_verified_feed({"feed_candidates": [{"source": "input-url-feed-fetch", "url": "x"}]}) is True,
                  "input-url-feed-fetch = 검증됨"))
    cases.append(("unverified_path_only",
                  _has_verified_feed({"feed_candidates": [{"source": "input-url-feed-path", "url": "x"}]}) is False,
                  "path 모양만 = 미검증"))
    cases.append(("unverified_well_known_non200",
                  _has_verified_feed({"feed_candidates": [
                      {"source": "well-known-path", "status": 403, "content_type": "application/xml"}]}) is False,
                  "well-known 403 = 미검증"))
    cases.append(("verified_empty",
                  _has_verified_feed({"feed_candidates": []}) is False, "후보 없음 = 미검증"))

    return cases


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    results = run()
    failed = [(n, d) for n, ok, d in results if not ok]
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {d}")
    if failed:
        print(f"\n{len(failed)} FAILED")
        sys.exit(1)
    print(f"\n{len(results)} passed")
