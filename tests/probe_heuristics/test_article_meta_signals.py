"""probe.extract.article_meta_signals — 페이지의 *단일 article* 명시 meta 신호 추출.

og:type=article + schema.org JSON-LD `@type` (NewsArticle/Article/BlogPosting/...) + microdata itemtype.
register.py 의 `_meta_article_diverging_check` gate 가 이 신호 + first_article_url path 발산 결합하여
recognize_reject 미커버 호스트의 단일 article 페이지 거부.

false positive 0 필수 — 보드 페이지에 의도치 않은 article 마크업 박혔어도 *path-prefix 매칭* gate 가
첫 segment 같으면 통과 (omate 등). 그래도 heuristic 자체는 신호 dict 를 돌려주므로 정확해야 함.
"""
from __future__ import annotations


_OG_ARTICLE_HTML = """
<!doctype html><html><head>
  <meta property="og:type" content="article">
  <title>Single Article</title>
</head><body><article>본문</article></body></html>
"""

_NEWS_ARTICLE_JSONLD = """
<!doctype html><html><head>
  <script type="application/ld+json">
  {"@context":"https://schema.org","@type":"NewsArticle","headline":"Test","author":{"@type":"Person","name":"A"}}
  </script>
</head><body><article>본문</article></body></html>
"""

_NESTED_GRAPH_JSONLD = """
<!doctype html><html><head>
  <script type="application/ld+json">
  {"@context":"https://schema.org","@graph":[
    {"@type":"WebPage","name":"x"},
    {"@type":"BlogPosting","headline":"Y"}
  ]}
  </script>
</head><body><article>본문</article></body></html>
"""

_MICRODATA_ARTICLE = """
<!doctype html><html><body>
  <article itemscope itemtype="https://schema.org/Article">
    <h1 itemprop="headline">제목</h1>
  </article>
</body></html>
"""

_BOTH_OG_AND_SCHEMA = """
<!doctype html><html><head>
  <meta property="og:type" content="article">
  <script type="application/ld+json">
  {"@context":"https://schema.org","@type":"NewsArticle","headline":"X"}
  </script>
</head><body></body></html>
"""

_NEUTRAL_BOARD = """
<!doctype html><html><head>
  <meta property="og:type" content="website">
  <title>게시판</title>
</head><body>
  <ul>
    <li><a href="/post/1">글1</a></li>
    <li><a href="/post/2">글2</a></li>
  </ul>
</body></html>
"""

_ITEMLIST_SCHEMA = """
<!doctype html><html><head>
  <script type="application/ld+json">
  {"@context":"https://schema.org","@type":"ItemList","itemListElement":[]}
  </script>
</head><body><ul><li><a href=/x>a</a></li></ul></body></html>
"""

_BROKEN_JSONLD = """
<!doctype html><html><head>
  <script type="application/ld+json">{ not valid json</script>
</head><body><article>x</article></body></html>
"""


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import article_meta_signals

    cases: list[tuple[str, bool, str]] = []

    # 1. og:type=article 만 — is_article_page=True.
    out = article_meta_signals(html=_OG_ARTICLE_HTML)
    cases.append(("og_article_only",
                  out is not None and out["has_og_article"] is True and out["is_article_page"] is True
                  and "og:type=article" in (out.get("signals") or []),
                  f"got {out!r}"))

    # 2. JSON-LD NewsArticle — is_article_page=True.
    out = article_meta_signals(html=_NEWS_ARTICLE_JSONLD)
    cases.append(("jsonld_newsarticle",
                  out is not None and out["is_article_page"] is True
                  and "NewsArticle" in (out.get("schema_article_types") or []),
                  f"got {out!r}"))

    # 3. JSON-LD @graph 안 BlogPosting — 재귀 추출.
    out = article_meta_signals(html=_NESTED_GRAPH_JSONLD)
    cases.append(("jsonld_graph_nested",
                  out is not None and out["is_article_page"] is True
                  and any("BlogPosting" == t for t in (out.get("schema_article_types") or [])),
                  f"got {out!r}"))

    # 4. microdata itemtype=schema.org/Article.
    out = article_meta_signals(html=_MICRODATA_ARTICLE)
    cases.append(("microdata_article",
                  out is not None and out["has_microdata_article"] is True
                  and out["is_article_page"] is True,
                  f"got {out!r}"))

    # 5. og:type + schema 둘 다 — signals 두 항목 모두 포함.
    out = article_meta_signals(html=_BOTH_OG_AND_SCHEMA)
    cases.append(("both_og_and_schema",
                  out is not None and out["has_og_article"] is True
                  and "NewsArticle" in (out.get("schema_article_types") or [])
                  and len(out.get("signals") or []) >= 2,
                  f"got {out!r}"))

    # 6. 보드 페이지 (og:type=website + 글 링크) — 신호 0건 → None.
    out = article_meta_signals(html=_NEUTRAL_BOARD)
    cases.append(("neutral_board_returns_none", out is None, f"got {out!r}"))

    # 7. ItemList schema 만 — article 타입 아님 → None.
    out = article_meta_signals(html=_ITEMLIST_SCHEMA)
    cases.append(("itemlist_schema_returns_none", out is None, f"got {out!r}"))

    # 8. 깨진 JSON-LD — 예외 안 던지고 None.
    out = article_meta_signals(html=_BROKEN_JSONLD)
    cases.append(("broken_jsonld_returns_none", out is None, f"got {out!r}"))

    # 9. 빈 html → None.
    out = article_meta_signals(html="")
    cases.append(("empty_html_returns_none", out is None, f"got {out!r}"))

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
