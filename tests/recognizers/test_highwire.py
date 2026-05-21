"""engine.recognizers.highwire — bioRxiv/medRxiv HighWire recent 목록 config."""
from __future__ import annotations

from pathlib import Path


_IGNORE = {"_recognized_platform", "_source_url", "_note", "_slug_board"}


def _functional(cfg: dict) -> dict:
    return {k: v for k, v in cfg.items() if k not in _IGNORE}


BIORXIV_EXPECTED = {
    "version": 1,
    "site": "biorxiv.org",
    "board": "biochemistry",
    "strategy": "httpx_html",
    "headers": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://www.biorxiv.org/content/early/recent",
        "Upgrade-Insecure-Requests": "1",
        "sec-ch-ua": "\"Chromium\";v=\"147\", \"Not.A/Brand\";v=\"8\"",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "\"Windows\"",
    },
    "timeout": 15,
    "list": {
        "url_template": "https://www.biorxiv.org/collection/{board}",
        "pagination": {"kind": "query_param", "page_param": "page"},
        "row_selector": "div.highwire-list-wrapper.highwire-article-citation-list div.highwire-article-citation.highwire-citation-type-highwire-article",
        "row_required_selector": "a.highwire-cite-linked-title",
        "include_notices": True,
        "fields": {
            "post_id": [{"from": "attr", "selector": ":self", "attr": "data-node-nid"}],
            "title": [{
                "from": "css",
                "selector": "a.highwire-cite-linked-title span.highwire-cite-title",
                "text": True,
                "transform": [["collapse_ws"]],
            }],
            "url": [{
                "from": "attr",
                "selector": "a.highwire-cite-linked-title",
                "attr": "href",
                "transform": [["urljoin", "https://www.biorxiv.org"]],
            }],
            "author": [{
                "from": "css",
                "selector": "span.highwire-citation-author",
                "text": True,
                "transform": [["collapse_ws"]],
            }],
            "category": [{"from": "const", "value": "Biochemistry"}],
            "published_at": [{
                "from": "css",
                "selector": "h3.highwire-list-title",
                "text": True,
                "transform": [["collapse_ws"], ["iso8601", ["%B %d, %Y"], "+00:00"]],
            }],
            "summary": [{
                "from": "css",
                "selector": "div.highwire-cite-metadata",
                "text": True,
                "transform": [["collapse_ws"]],
            }],
        },
    },
    "article": {
        "fetch_kind": "html",
        "content": [
            {"from": "css", "selector": "div.section.abstract", "html": True},
            {"from": "css", "selector": "div.abstract", "html": True},
            {"from": "css", "selector": "div#block-system-main .section", "html": True},
            {"from": "css", "selector": "div#block-system-main article", "html": True},
        ],
        "enrich": {
            "title": [{
                "from": "css",
                "selector": "h1#page-title",
                "text": True,
                "transform": [["collapse_ws"]],
            }],
            "published_at": [
                {
                    "from": "css",
                    "selector": "meta[name='citation_date']",
                    "attr": "content",
                    "transform": [["date_only_to_iso", "+00:00"]],
                },
                {
                    "from": "css",
                    "selector": "meta[name='DC.Date']",
                    "attr": "content",
                    "transform": [["date_only_to_iso", "+00:00"]],
                },
            ],
        },
    },
}

MEDRXIV_EXPECTED = {
    "version": 1,
    "site": "medrxiv.org",
    "board": "all",
    "strategy": "httpx_html",
    "headers": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://www.medrxiv.org/content/early/recent",
    },
    "timeout": 30,
    "polite_sleep": {"min": 7, "max": 9},
    "list": {
        "url_template": "https://www.medrxiv.org/content/early/recent",
        "pagination": {"kind": "query_param", "page_param": "page"},
        "row_selector": "div.highwire-list-wrapper.highwire-article-citation-list > div.highwire-list > ul > li",
        "row_required_selector": "a.highwire-cite-linked-title",
        "fields": {
            "post_id": [{
                "from": "attr",
                "selector": "div.highwire-article-citation",
                "attr": "data-pisa-master",
                "transform": [["regex_extract", "^medrxiv;(.+)$"]],
            }],
            "title": [{
                "from": "css",
                "selector": "a.highwire-cite-linked-title span.highwire-cite-title",
                "text": True,
                "transform": [["collapse_ws"], ["strip"]],
            }],
            "url": [{
                "from": "attr",
                "selector": "a.highwire-cite-linked-title",
                "attr": "href",
                "transform": [["urljoin", "https://www.medrxiv.org"]],
            }],
            "published_at": [{
                "from": "attr",
                "selector": "div.highwire-article-citation",
                "attr": "data-pisa",
                "transform": [
                    ["regex_extract", r"^medrxiv;(\d{4}\.\d{2}\.\d{2})\."],
                    ["replace", ".", "-"],
                    ["date_only_to_iso", "+09:00"],
                ],
            }],
            "author": [{
                "from": "css",
                "selector": "span.highwire-citation-author.first",
                "text": True,
                "transform": [["collapse_ws"]],
            }],
            "summary": [{
                "from": "css",
                "selector": "div.highwire-cite-metadata span.highwire-cite-metadata-doi",
                "text": True,
                "transform": [["collapse_ws"]],
            }],
        },
    },
    "article": {
        "fetch_kind": "html",
        "content": [
            {"from": "css", "selector": "div.section-abstract", "html": True},
            {"from": "css", "selector": "div#block-system-main .section.abstract", "html": True},
            {"from": "css", "selector": "div#block-system-main", "html": True},
        ],
        "enrich": {
            "title": [{
                "from": "css",
                "selector": "h1#page-title",
                "text": True,
                "transform": [["collapse_ws"]],
            }],
            "published_at": [{
                "from": "css",
                "selector": "div.highwire-cite-metadata span.highwire-cite-metadata-pages",
                "text": True,
                "transform": [
                    ["regex_extract", r"^(\d{4}\.\d{2}\.\d{2})"],
                    ["replace", ".", "-"],
                    ["date_only_to_iso", "+09:00"],
                ],
            }],
        },
    },
}


def run() -> list[tuple[str, bool, str]]:
    from engine.recognizers import recognize, recognize_reject
    from engine.recognizers.highwire import PATTERNS, _build

    pat = PATTERNS[0][0]

    def _try(url: str):
        m = pat.search(url)
        return _build(m, url) if m else None

    cases: list[tuple[str, bool, str]] = []

    biorxiv_url = "https://www.biorxiv.org/content/early/recent"
    medrxiv_url = "https://www.medrxiv.org/content/early/recent"

    for label, url, expected in [
        ("biorxiv", biorxiv_url, BIORXIV_EXPECTED),
        ("medrxiv", medrxiv_url, MEDRXIV_EXPECTED),
    ]:
        built = _try(url)
        ok = built is not None and _functional(built) == expected
        if built is None:
            detail = "builder None"
        else:
            diffs = [k for k in set(_functional(built)) | set(expected)
                     if _functional(built).get(k) != expected.get(k)]
            detail = "all reproduced" if not diffs else f"diff keys {diffs}"
        cases.append((f"roundtrip_{label}", ok, detail))

    cfg = recognize(biorxiv_url)
    cases.append(("recognize_biorxiv",
                  cfg is not None and cfg.get("_recognized_platform") == "highwire",
                  f"got {cfg and cfg.get('_recognized_platform')!r}"))

    cfg = recognize(medrxiv_url)
    cases.append(("recognize_medrxiv",
                  cfg is not None and cfg.get("_recognized_platform") == "highwire",
                  f"got {cfg and cfg.get('_recognized_platform')!r}"))

    other_host = recognize("https://example.com/content/early/recent")
    cases.append(("other_host_negative", other_host is None, f"got {other_host}"))

    same_host_neg = [
        "https://www.biorxiv.org/content/10.1101/2026.05.01.123456v1",
        "https://www.medrxiv.org/content/10.1101/2026.05.01.123456v1",
        "https://www.biorxiv.org/content/early",
        "https://www.medrxiv.org/about",
    ]
    for url in same_host_neg:
        r = recognize(url)
        hit = r is not None and r.get("_recognized_platform") == "highwire"
        cases.append((f"same_host_neg:{url}", not hit, f"got {r and r.get('_recognized_platform')!r}"))

    for url in [biorxiv_url, medrxiv_url]:
        reject = recognize_reject(url)
        cases.append((f"no_reject_conflict:{url}", reject is None, f"got {reject!r}"))

    return cases


def test_highwire_run_protocol():
    failed = [(name, detail) for name, ok, detail in run() if not ok]
    assert not failed


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    results = run()
    failed = [(n, d) for n, ok, d in results if not ok]
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {d}")
    if failed:
        print(f"\n{len(failed)} FAILED")
        sys.exit(1)
    print(f"\n{len(results)} passed")
