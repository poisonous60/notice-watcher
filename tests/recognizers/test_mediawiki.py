"""engine.recognizers.mediawiki -- MediaWiki RecentChanges config."""
from __future__ import annotations

from pathlib import Path

MEMBERS = {
    "de": (
        "https://de.wikipedia.org/wiki/Spezial:Letzte_%C3%84nderungen",
        "de.wikipedia.org",
        "Spezial:Letzte_%C3%84nderungen",
    ),
    "fr": (
        "https://fr.wikipedia.org/wiki/Sp%C3%A9cial:Modifications_r%C3%A9centes",
        "fr.wikipedia.org",
        "Sp%C3%A9cial:Modifications_r%C3%A9centes",
    ),
    "ja": (
        "https://ja.wikipedia.org/wiki/%E7%89%B9%E5%88%A5:%E6%9C%80%E8%BF%91%E3%81%AE%E6%9B%B4%E6%96%B0",
        "ja.wikipedia.org",
        "%E7%89%B9%E5%88%A5:%E6%9C%80%E8%BF%91%E3%81%AE%E6%9B%B4%E6%96%B0",
    ),
    "ko": (
        "https://ko.wikipedia.org/wiki/%ED%8A%B9%EC%88%98:%EC%B5%9C%EA%B7%BC%EB%B0%94%EB%80%9C",
        "ko.wikipedia.org",
        "%ED%8A%B9%EC%88%98:%EC%B5%9C%EA%B7%BC%EB%B0%94%EB%80%9C",
    ),
    "zh": (
        "https://zh.wikipedia.org/wiki/Special:%E6%9C%80%E8%BF%91%E6%9B%B4%E6%94%B9",
        "zh.wikipedia.org",
        "Special:%E6%9C%80%E8%BF%91%E6%9B%B4%E6%94%B9",
    ),
    "commons": (
        "https://commons.wikimedia.org/wiki/Special:RecentChanges",
        "commons.wikimedia.org",
        "Special:RecentChanges",
    ),
    "enwiki": (
        "https://en.wikipedia.org/wiki/Special:RecentChanges",
        "en.wikipedia.org",
        "Special:RecentChanges",
    ),
    "enwiktionary": (
        "https://en.wiktionary.org/wiki/Special:RecentChanges",
        "en.wiktionary.org",
        "Special:RecentChanges",
    ),
}


def run() -> list[tuple[str, bool, str]]:
    from engine.recognizers import recognize, recognize_reject
    from engine.recognizers.mediawiki import PATTERNS, _build

    pat = PATTERNS[0][0]
    cases: list[tuple[str, bool, str]] = []

    for label, (url, host, title) in MEMBERS.items():
        m = pat.search(url)
        cfg = _build(m, url) if m else None
        expected = {
            "site": host,
            "board": "RecentChanges",
            "_slug_board": "RecentChanges",
            "strategy": "httpx_html",
            "list_url": f"https://{host}/w/index.php?title={title}&limit=50",
            "row_selector": "li.mw-changeslist-line",
            "row_required_selector": "a.mw-changeslist-title",
            "title_selector": "a.mw-changeslist-title",
            "url_join": f"https://{host}",
        }
        got = {
            "site": cfg and cfg.get("site"),
            "board": cfg and cfg.get("board"),
            "_slug_board": cfg and cfg.get("_slug_board"),
            "strategy": cfg and cfg.get("strategy"),
            "list_url": cfg and cfg["list"].get("url_template"),
            "row_selector": cfg and cfg["list"].get("row_selector"),
            "row_required_selector": cfg and cfg["list"].get("row_required_selector"),
            "title_selector": cfg and cfg["list"]["fields"]["title"][0].get("selector"),
            "url_join": cfg and cfg["list"]["fields"]["url"][0]["transform"][0][1],
        }
        cases.append((f"roundtrip_signature[{label}]", got == expected, f"got {got!r}"))

        rcfg = recognize(url)
        cases.append(
            (f"recognize_integration[{label}]",
             rcfg is not None and rcfg.get("_recognized_platform") == "mediawiki",
             f"got {rcfg and rcfg.get('_recognized_platform')!r}"),
        )

        reject = recognize_reject(url)
        cases.append((f"reject_none[{label}]", reject is None, f"got {reject!r}"))

    query_url = "https://en.wikipedia.org/w/index.php?title=Special:RecentChanges&limit=50"
    qcfg = recognize(query_url)
    cases.append(("index_php_title_form",
                  qcfg is not None and qcfg["site"] == "en.wikipedia.org",
                  f"got {qcfg and qcfg.get('site')!r}"))

    for url in [
        "https://en.wikipedia.org/wiki/Python",
        "https://en.wikipedia.org/wiki/Special:Watchlist",
        "https://de.wikipedia.org/wiki/Hauptseite",
        "https://commons.wikimedia.org/wiki/File:Example.jpg",
        "https://www.mediawiki.org/wiki/Special:RecentChanges",
        "https://example.org/wiki/Special:RecentChanges",
    ]:
        cfg = recognize(url)
        hit = cfg is not None and cfg.get("_recognized_platform") == "mediawiki"
        cases.append((f"negative[{url.split('://', 1)[1][:32]}]", not hit,
                      f"recognize -> {cfg and cfg.get('_recognized_platform')!r}"))

    # Builder must not leak host-specific mutation through the shared skeleton.
    en_cfg = recognize(MEMBERS["enwiki"][0])
    fr_cfg = recognize(MEMBERS["fr"][0])
    ok = (
        en_cfg is not None
        and fr_cfg is not None
        and en_cfg["list"]["fields"]["url"][0]["transform"][0][1] == "https://en.wikipedia.org"
        and fr_cfg["list"]["fields"]["url"][0]["transform"][0][1] == "https://fr.wikipedia.org"
    )
    cases.append(("no_mutation_leak", ok, "urljoin base should remain host-specific"))

    return cases


def test_mediawiki_recognizer() -> None:
    failed = [(name, detail) for name, ok, detail in run() if not ok]
    assert not failed, failed


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
