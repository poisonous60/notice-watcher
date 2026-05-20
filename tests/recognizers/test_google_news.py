"""engine.recognizers.google_news — Google 검색 SERP + News RSS 피드 인식.

search (q=) → rss/search 합성 (기존). top-stories `/rss` · topic `/rss/topics/<id>` ·
section `/rss/headlines/...` → feed_url 직접 (2026-05-20-b fix). `/rss/articles/<id>`(단일 글)·
`/rss/search`(검색) 경계 검증.
"""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from engine.recognizers import recognize
    from engine.config_schema import validate_config
    from adapters import GoogleNewsRssAdapter

    cases: list[tuple[str, bool, str]] = []

    def _kind(r):
        if r is None:
            return "none"
        kw = r.get("kwargs") or {}
        return "search" if "query" in kw and not kw.get("feed_url") else ("feed" if kw.get("feed_url") else "?")

    # 1. top-stories `/rss` (검색 아님) → feed 모드, board=top_<hl>_<gl>
    r = recognize("https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko")
    ok = r is not None and _kind(r) == "feed" and r.get("board") == "top_ko_KR"
    if ok:
        validate_config(r)
    cases.append(("gnews_top_stories", ok, f"got {None if r is None else (r.get('board'), _kind(r))}"))

    # 2. search `/rss/search?q=` → search 모드 (기존 후방호환)
    r = recognize("https://news.google.com/rss/search?q=%EA%B2%8C%EC%9E%84")
    cases.append(("gnews_search_backcompat", r is not None and _kind(r) == "search",
                  f"got {None if r is None else _kind(r)}"))

    # 3. topic `/rss/topics/<id>` → feed 모드
    r = recognize("https://news.google.com/rss/topics/CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFp1ZEdvU0FtdHZLQUFQAQ")
    cases.append(("gnews_topic_feed", r is not None and _kind(r) == "feed" and r.get("board", "").startswith("topic_"),
                  f"got {None if r is None else (r.get('board'), _kind(r))}"))

    # 4. section `/rss/headlines/section/topic/<NAME>` → feed 모드, board=name
    r = recognize("https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-US&gl=US")
    cases.append(("gnews_section_feed", r is not None and _kind(r) == "feed" and r.get("board") == "technology",
                  f"got {None if r is None else (r.get('board'), _kind(r))}"))

    # 5. 단일 기사 `/rss/articles/<id>` → 미인식 (등록 대상 X)
    r = recognize("https://news.google.com/rss/articles/CBMiabcdef")
    cases.append(("gnews_article_not_recognized", r is None, f"got {r!r}"))

    # 6. 어댑터 feed_url 모드 — query 없이 init 가능 (back-compat: query OR feed_url)
    try:
        a = GoogleNewsRssAdapter(feed_url="https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko", board="top_ko_KR")
        ok6 = a._feed_url == "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko" and a.board == "top_ko_KR"
    except Exception as e:  # noqa: BLE001
        ok6 = False
        e = str(e)
    cases.append(("gnews_adapter_feed_url_mode", ok6, "feed_url 직접 사용 + board"))

    # 7. 어댑터 — query/feed_url 둘 다 없으면 ValueError (회귀 가드)
    try:
        GoogleNewsRssAdapter()
        ok7 = False
    except ValueError:
        ok7 = True
    except Exception:  # noqa: BLE001
        ok7 = False
    cases.append(("gnews_adapter_requires_one", ok7, "query 또는 feed_url 필수"))

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
