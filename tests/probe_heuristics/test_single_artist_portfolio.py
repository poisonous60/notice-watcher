"""engine.digest.detect_single_artist_portfolio — personal portfolio structural signal."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


_NCASE_STYLE_HTML = """<html><head><title>It's Nicky Case!</title></head><body>
<nav>
  <a href="https://blog.ncase.me/">blog</a>
  <a href="/faq">faq/contact</a>
</nav>
<main>
  <h1>SHTUFF YOU CAN PLAY</h1>
  <p>i make shtuff for curious & playful peeps</p>
  <div class="grid">
    <a href="/anxiety/">Adventures With Anxiety</a>
    <a href="/fireflies/">Fireflies</a>
    <a href="/joy/">The Joy of Why</a>
    <a href="/trust/">The Evolution of Trust</a>
  </div>
</main>
</body></html>"""


_NEWS_BOARD_HTML = """<html><head><title>WayForward News</title></head><body>
<main>
  <h1>News</h1>
  <article><a href="/news/river-city-girls-update/">River City Girls Update</a><time>2026</time></article>
  <article><a href="/news/new-release-date/">New Release Date</a><time>2026</time></article>
  <article><a href="/news/patch-notes/">Patch Notes</a><time>2026</time></article>
  <article><a href="/news/convention-lineup/">Convention Lineup</a><time>2026</time></article>
</main>
</body></html>"""


def run() -> list[tuple[str, bool, str]]:
    from engine.digest import detect_single_artist_portfolio
    from generate.classify import _struct_hint

    cases: list[tuple[str, bool, str]] = []

    out = detect_single_artist_portfolio(
        _NCASE_STYLE_HTML,
        "https://ncase.me/",
        {"html_repeating_patterns": [{"child_count": 4, "sample_url": "https://ncase.me/anxiety/"}]},
    )
    cases.append(("ncase_style_detected",
                  isinstance(out, dict) and out.get("detected") is True
                  and out.get("grid_item_count") == 4
                  and "blog.ncase.me" in str(out.get("blog_link")),
                  f"got {out!r}"))

    h = _struct_hint({"single_artist_portfolio": out, "list_candidates": {}}, "https://ncase.me/")
    cases.append(("struct_hint_mentions_portfolio",
                  "single-artist portfolio" in h and "canonical blog" in h,
                  f"h={h}"))

    board = detect_single_artist_portfolio(
        _NEWS_BOARD_HTML,
        "https://wayforward.com/news/",
        {"html_repeating_patterns": [{"child_count": 4, "sample_url": "https://wayforward.com/news/river-city-girls-update/"}]},
    )
    cases.append(("news_board_not_detected", board is None, f"got {board!r}"))

    no_blog = _NCASE_STYLE_HTML.replace("https://blog.ncase.me/", "/about/")
    out2 = detect_single_artist_portfolio(
        no_blog,
        "https://ncase.me/",
        {"html_repeating_patterns": [{"child_count": 4, "sample_url": "https://ncase.me/anxiety/"}]},
    )
    cases.append(("requires_blog_escape_hatch", out2 is None, f"got {out2!r}"))

    return cases


if __name__ == "__main__":
    import sys

    results = run()
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {d}")
    failed = [r for r in results if not r[1]]
    if failed:
        print(f"\n{len(failed)} FAILED")
        sys.exit(1)
    print(f"\n{len(results)} passed")
