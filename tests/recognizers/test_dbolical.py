"""engine.recognizers.dbolical - IndieDB/ModDB news RSS config."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from engine.config_schema import validate_config
    from engine.recognizers import recognize

    cases: list[tuple[str, bool, str]] = []

    indie = recognize("https://indiedb.com/news/")
    cases.append((
        "indiedb_news_recognized",
        indie is not None and indie.get("_recognized_platform") == "dbolical",
        f"got {indie and indie.get('_recognized_platform')!r}",
    ))
    cases.append((
        "indiedb_rss_url",
        indie is not None
        and indie["list"]["url_template"] == "https://rss.indiedb.com/news/feed/rss.xml"
        and indie.get("_slug_board") == "indiedb_news",
        f"got {indie and indie.get('list', {}).get('url_template')!r} slug={indie and indie.get('_slug_board')!r}",
    ))

    moddb = recognize("https://www.moddb.com/news")
    cases.append((
        "moddb_news_recognized",
        moddb is not None
        and moddb["site"] == "moddb.com"
        and moddb["list"]["url_template"] == "https://rss.moddb.com/news/feed/rss.xml"
        and moddb.get("_slug_board") == "moddb_news",
        f"got site={moddb and moddb.get('site')!r} url={moddb and moddb.get('list', {}).get('url_template')!r}",
    ))

    direct = recognize("https://rss.indiedb.com/news/feed/rss.xml")
    cases.append((
        "direct_rss_recognized",
        direct is not None and direct["site"] == "indiedb.com",
        f"got {direct and direct.get('site')!r}",
    ))

    if indie is not None:
        try:
            validate_config(indie)
            cases.append(("schema_valid", True, ""))
        except Exception as e:  # noqa: BLE001
            cases.append(("schema_valid", False, f"{type(e).__name__}: {e}"))

    negatives = [
        "https://www.indiedb.com/games/equation-of-humanity/news/under-honor-games-authority",
        "https://www.moddb.com/games/project-swap-sound/news/look-at-the-fixes",
        "https://www.indiedb.com/games",
        "https://rss.indiedb.com/games/feed/rss.xml",
        "https://www.desura.com/news/",
    ]
    for url in negatives:
        cfg = recognize(url)
        hit = cfg is not None and cfg.get("_recognized_platform") == "dbolical"
        cases.append((f"negative[{url.split('//', 1)[1][:36]}]", not hit, f"got {cfg and cfg.get('_recognized_platform')!r}"))

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
