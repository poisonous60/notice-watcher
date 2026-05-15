"""probe.extract.runtime_id_candidates — HTML 안 런타임 ID/슬러그 후보 추출."""
from __future__ import annotations


def run() -> list[tuple[str, bool, str]]:
    from probe.extract import runtime_id_candidates

    cases: list[tuple[str, bool, str]] = []

    # 1. js_var — 네이버 카페 g_sClubId 정규식
    html = """
    <script>
      var g_sUserId = "";
      var g_sClubId = "31104609";
      var g_sCafeName = "gutterlife";
    </script>
    """
    out = runtime_id_candidates(html)
    has_clubid = any(c["name"].lower() == "g_sclubid" and c["value"] == "31104609"
                     and c["source"] == "js_var" for c in out)
    cases.append(("js_var_naver_clubid", has_clubid, f"got {[(c['name'], c['value'], c['source']) for c in out]!r}"))

    # 2. js_var — `var boardId = 1018` (따옴표 없는 정수)
    html = "<script>var boardId = 1018; var foo = 'bar';</script>"
    out = runtime_id_candidates(html)
    cases.append(("js_var_int_unquoted",
                  any(c["name"] == "boardId" and c["value"] == "1018" for c in out),
                  f"got {out!r}"))

    # 3. js_var — `"cafeId": "123"` (JSON-스타일 key)
    html = '<script>window.__CONFIG = {"cafeId": "123", "title": "hi"};</script>'
    out = runtime_id_candidates(html)
    cases.append(("js_var_json_key",
                  any(c["name"] == "cafeId" and c["value"] == "123" for c in out),
                  f"got {out!r}"))

    # 4. 화이트리스트 외 변수는 안 잡힘 — 노이즈 차단
    html = "<script>var randomVar = 42; var unrelatedThing = 100;</script>"
    out = runtime_id_candidates(html)
    cases.append(("non_id_var_skipped",
                  not any(c["name"] in ("randomVar", "unrelatedThing") for c in out),
                  f"got {out!r}"))

    # 5. 단일 자리 정수는 ID 후보로 부족 (_ID_INT_RE = \d{2,})
    html = "<script>var boardId = 1;</script>"
    out = runtime_id_candidates(html)
    cases.append(("single_digit_skipped",
                  not any(c["name"] == "boardId" and c["value"] == "1" for c in out),
                  f"got {out!r}"))

    # 6. next_data — __NEXT_DATA__ 안 *Id 키
    html = """
    <html><body>
    <script id="__NEXT_DATA__" type="application/json">
    {"props":{"pageProps":{"boardId":1018,"forumName":"bluearchive","articleId":"abc-123"}}}
    </script>
    </body></html>
    """
    out = runtime_id_candidates(html)
    has_board = any(c["source"] == "next_data" and "boardId" in c["name"] and c["value"] == "1018" for c in out)
    has_article = any(c["source"] == "next_data" and "articleId" in c["name"] and c["value"] == "abc-123" for c in out)
    cases.append(("next_data_boardId", has_board, f"got {[(c['name'], c['value'], c['source']) for c in out]!r}"))
    cases.append(("next_data_articleId_slug", has_article, f"got {[(c['name'], c['value'], c['source']) for c in out]!r}"))

    # 7. meta og:url path 끝 segment (정수)
    html = '<html><head><meta property="og:url" content="https://x.com/boards/1234"></head></html>'
    out = runtime_id_candidates(html)
    cases.append(("meta_og_url_int_segment",
                  any(c["source"] == "meta_og_url" and c["value"] == "1234" for c in out),
                  f"got {out!r}"))

    # 8. meta og:url 끝 segment 가 slug (정수 아님) → 안 잡힘 (정수만 받음 — 슬러그 후보는 노이즈 多)
    html = '<html><head><meta property="og:url" content="https://x.com/community/about"></head></html>'
    out = runtime_id_candidates(html)
    cases.append(("meta_og_url_slug_skipped",
                  not any(c["source"] == "meta_og_url" for c in out),
                  f"got {out!r}"))

    # 8b. meta og:url content-first attribute order — bs4 가 잡아야 (이전 regex 는 silent miss)
    html = '<html><head><meta content="https://x.com/boards/5678" property="og:url"></head></html>'
    out = runtime_id_candidates(html)
    cases.append(("meta_og_url_attr_order_agnostic",
                  any(c["source"] == "meta_og_url" and c["value"] == "5678" for c in out),
                  f"got {out!r}"))

    # 9. 빈 HTML
    cases.append(("empty_html", runtime_id_candidates("") == [], ""))

    # 10. 결정성 — 같은 입력 같은 출력
    html = "<script>var g_sClubId = '31104609'; var boardId = 1018;</script>"
    a = runtime_id_candidates(html)
    b = runtime_id_candidates(html)
    cases.append(("deterministic", a == b, f"a={a!r} b={b!r}"))

    return cases
